"""记忆管理器 — 读写与 RAG 上下文拼接（Sprint 4 T-4.2/T-4.3 + 3.4 总结）"""

import asyncio
import logging
import threading
import uuid
from datetime import datetime
from typing import Protocol

from lingji_agent.foundation.config import MemoryConfig
from lingji_agent.memory.decay import apply_decay_ranking, prune_stale_memories
from lingji_agent.memory.summarizer import maybe_run_summarization, should_run_summarization

logger = logging.getLogger(__name__)


class MemoryBackend(Protocol):
    def retrieve_context(
        self,
        current_query: str,
        *,
        episodic_thread_id: str | None = None,
    ) -> str: ...

    async def save_episodic_memory(
        self,
        thread_id: str,
        role: str,
        content: str,
        tool_output: str | None = None,
    ) -> None: ...

    async def save_user_preference(self, preference_key: str, preference_value: str) -> None: ...

    async def warmup(self) -> None: ...


class NullMemoryManager:
    """记忆层关闭时的零开销实现"""

    def retrieve_context(
        self,
        current_query: str,
        *,
        episodic_thread_id: str | None = None,
    ) -> str:
        return ""

    async def save_episodic_memory(
        self,
        thread_id: str,
        role: str,
        content: str,
        tool_output: str | None = None,
    ) -> None:
        return None

    async def save_user_preference(self, preference_key: str, preference_value: str) -> None:
        return None

    async def warmup(self) -> None:
        return None


class MemoryManager:
    """ChromaDB 记忆管理：懒加载向量库、异步写入、同步检索"""

    def __init__(self, config: MemoryConfig, vector_store=None, llm_connector=None):
        self._config = config
        self._store = vector_store
        self._llm_connector = llm_connector
        self._init_lock = threading.Lock()
        self._ready = vector_store is not None

    def _ensure_store(self):
        if self._store is not None:
            return self._store
        with self._init_lock:
            if self._store is None:
                from lingji_agent.memory.vector_store import LocalVectorStore

                logger.info("记忆层正在初始化 ChromaDB（首次可能需下载 ONNX 模型）...")
                self._store = LocalVectorStore(db_path=self._config.db_path)
                self._ready = True
                logger.info("记忆层向量库已就绪 (db=%s)", self._config.db_path)
            return self._store

    async def warmup(self) -> None:
        """后台预热，避免阻塞 Gateway 连接。"""
        if not self._ready:
            await asyncio.to_thread(self._ensure_store)
        if self._config.summarize_enabled:
            store = self._ensure_store()
            should_run_summarization(store, self._config)

    async def _after_episodic_write(self) -> None:
        try:
            store = self._ensure_store()
            prune_stale_memories(store, self._config)
            await maybe_run_summarization(store, self._llm_connector, self._config)
        except Exception as exc:
            logger.warning("记忆层后处理失败: %s", exc)

    async def save_episodic_memory(
        self,
        thread_id: str,
        role: str,
        content: str,
        tool_output: str | None = None,
    ) -> None:
        doc_id = str(uuid.uuid4())
        text = f"[{role.upper()}]: {content}"
        if tool_output:
            max_chars = self._config.tool_output_max_chars
            text += f"\n[TOOL_OUTPUT]: {tool_output[:max_chars]}"

        metadata = {
            "thread_id": thread_id,
            "timestamp": datetime.now().isoformat(),
            "type": "conversation",
        }

        async def _write():
            store = self._ensure_store()
            store.add_memory("episodic", doc_id, text, metadata)
            await self._after_episodic_write()

        asyncio.create_task(_write())

    async def save_user_preference(self, preference_key: str, preference_value: str) -> None:
        doc_id = f"pref_{preference_key}"
        text = f"User Preference: {preference_key} is {preference_value}"
        metadata = {"type": "preference", "key": preference_key}

        async def _write():
            store = self._ensure_store()
            store.add_memory("semantic", doc_id, text, metadata)

        asyncio.create_task(_write())

    def retrieve_context(
        self,
        current_query: str,
        *,
        episodic_thread_id: str | None = None,
    ) -> str:
        if not self._ready and self._store is None:
            return ""
        store = self._ensure_store()
        fetch_semantic = max(self._config.semantic_top_k * 2, self._config.semantic_top_k)
        fetch_episodic = max(self._config.episodic_top_k * 2, self._config.episodic_top_k)

        prefs = apply_decay_ranking(
            store.search("semantic", current_query, top_k=fetch_semantic),
            decay_enabled=False,
            decay_lambda=self._config.decay_lambda,
            top_k=self._config.semantic_top_k,
        )

        episodic_filter = (
            {"thread_id": episodic_thread_id} if episodic_thread_id else None
        )
        episodes = apply_decay_ranking(
            store.search(
                "episodic",
                current_query,
                top_k=fetch_episodic,
                metadata_filter=episodic_filter,
            ),
            decay_enabled=self._config.decay_enabled,
            decay_lambda=self._config.decay_lambda,
            top_k=self._config.episodic_top_k,
        )
        if episodic_thread_id:
            episodes = [
                ep for ep in episodes
                if ep.get("metadata", {}).get("thread_id") == episodic_thread_id
            ]

        context_parts: list[str] = []

        if prefs:
            context_parts.append("<user_preferences>")
            for pref in prefs:
                context_parts.append(f"- {pref['content']}")
            context_parts.append("</user_preferences>")

        if episodes:
            context_parts.append("<relevant_history>")
            for episode in episodes:
                context_parts.append(f"- {episode['content']}")
            context_parts.append("</relevant_history>")

        return "\n".join(context_parts)


def create_memory_manager(config: MemoryConfig, llm_connector=None) -> MemoryBackend:
    """按配置创建记忆管理器；初始化失败时降级为 NullMemoryManager"""
    if not config.enabled:
        return NullMemoryManager()

    try:
        return MemoryManager(config, llm_connector=llm_connector)
    except Exception as exc:
        logger.warning("记忆层初始化失败，已降级关闭: %s", exc)
        return NullMemoryManager()
