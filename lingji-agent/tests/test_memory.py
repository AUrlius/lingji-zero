"""记忆层单元测试 — Sprint 4"""

import asyncio
import hashlib
import os
import tempfile

import pytest
import yaml

from lingji_agent.foundation.config import AgentConfig, MemoryConfig, load_config
from lingji_agent.memory.manager import (
    MemoryManager,
    NullMemoryManager,
    create_memory_manager,
)
from lingji_agent.memory.vector_store import LocalVectorStore


class MockEmbedder:
    """确定性 mock embedder，避免测试下载 ONNX 模型"""

    def __call__(self, input: list[str]) -> list[list[float]]:
        vectors = []
        for text in input:
            digest = hashlib.md5(text.encode()).digest()
            vec = [float(b) / 255.0 for b in digest]
            vec.extend([0.0] * (384 - len(vec)))
            vectors.append(vec[:384])
        return vectors

    def name(self) -> str:
        return "mock_embedder"


@pytest.fixture
def temp_db_path():
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


@pytest.fixture
def vector_store(temp_db_path):
    return LocalVectorStore(temp_db_path, embedding_function=MockEmbedder())


class TestNullMemoryManager:
    def test_retrieve_returns_empty(self):
        mgr = NullMemoryManager()
        assert mgr.retrieve_context("anything") == ""

    @pytest.mark.asyncio
    async def test_save_is_noop(self):
        mgr = NullMemoryManager()
        await mgr.save_episodic_memory("t1", "user", "hello")
        await mgr.save_user_preference("lang", "python")


class TestLocalVectorStore:
    def test_add_and_search_episodic(self, vector_store):
        vector_store.add_memory(
            "episodic",
            "doc-1",
            "[USER]: fix bug in auth module",
            {"thread_id": "t1"},
        )
        results = vector_store.search("episodic", "auth bug", top_k=1)
        assert len(results) == 1
        assert "auth module" in results[0]["content"]

    def test_add_and_search_semantic(self, vector_store):
        vector_store.add_memory(
            "semantic",
            "pref_lang",
            "User Preference: preferred_language is typescript",
            {"type": "preference"},
        )
        results = vector_store.search("semantic", "typescript preference", top_k=1)
        assert len(results) == 1
        assert "typescript" in results[0]["content"]

    def test_search_empty_collection(self, vector_store):
        assert vector_store.search("episodic", "query", top_k=3) == []


class TestMemoryManager:
    def test_retrieve_context_formats_xml(self, vector_store):
        vector_store.add_memory(
            "semantic",
            "pref_pkg",
            "User Preference: package_manager is pnpm",
            {"type": "preference"},
        )
        vector_store.add_memory(
            "episodic",
            "ep-1",
            "[USER]: 帮我写脚本",
            {"thread_id": "t1"},
        )

        mgr = MemoryManager(MemoryConfig(), vector_store=vector_store)
        context = mgr.retrieve_context("写脚本用什么包管理器")

        assert "<user_preferences>" in context
        assert "pnpm" in context
        assert "<relevant_history>" in context
        assert "写脚本" in context

    def test_retrieve_context_empty(self, vector_store):
        mgr = MemoryManager(MemoryConfig(), vector_store=vector_store)
        assert mgr.retrieve_context("hello") == ""

    def test_lazy_init_no_store_until_warmup(self):
        mgr = MemoryManager(MemoryConfig())
        assert mgr._store is None
        assert mgr.retrieve_context("hello") == ""

    @pytest.mark.asyncio
    async def test_warmup_initializes_store(self, temp_db_path):
        store = LocalVectorStore(temp_db_path, embedding_function=MockEmbedder())
        mgr = MemoryManager(MemoryConfig(), vector_store=store)
        await mgr.warmup()
        assert mgr._ready is True

    @pytest.mark.asyncio
    async def test_save_episodic_memory_persists(self, temp_db_path):
        store = LocalVectorStore(temp_db_path, embedding_function=MockEmbedder())
        mgr = MemoryManager(MemoryConfig(), vector_store=store)

        await mgr.save_episodic_memory("thread-a", "user", "remember this fact")
        await asyncio.sleep(0.2)

        results = store.search("episodic", "remember fact", top_k=1)
        assert len(results) == 1
        assert "remember this fact" in results[0]["content"]

    @pytest.mark.asyncio
    async def test_save_user_preference_persists(self, temp_db_path):
        store = LocalVectorStore(temp_db_path, embedding_function=MockEmbedder())
        mgr = MemoryManager(MemoryConfig(), vector_store=store)

        await mgr.save_user_preference("editor", "vscode")
        await asyncio.sleep(0.2)

        results = store.search("semantic", "editor vscode", top_k=1)
        assert len(results) == 1
        assert "vscode" in results[0]["content"]


class TestCreateMemoryManager:
    def test_disabled_returns_null(self):
        mgr = create_memory_manager(MemoryConfig(enabled=False))
        assert isinstance(mgr, NullMemoryManager)

    def test_enabled_returns_manager(self, temp_db_path):
        cfg = MemoryConfig(enabled=True, db_path=temp_db_path)
        mgr = create_memory_manager(cfg)
        assert isinstance(mgr, MemoryManager)


class TestMemoryConfig:
    def test_defaults(self):
        cfg = AgentConfig()
        assert cfg.memory.enabled is True
        assert cfg.memory.episodic_top_k == 3
        assert cfg.memory.semantic_top_k == 2

    def test_yaml_loading(self):
        yaml_data = {
            "memory": {
                "enabled": False,
                "db_path": "/tmp/test-memory",
                "episodic_top_k": 5,
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(yaml_data, f)
            path = f.name

        try:
            cfg = load_config(path)
            assert cfg.memory.enabled is False
            assert cfg.memory.db_path == "/tmp/test-memory"
            assert cfg.memory.episodic_top_k == 5
            assert cfg.memory.semantic_top_k == 2
        finally:
            os.unlink(path)

    def test_env_memory_enabled(self):
        os.environ["LINGJI_MEMORY_ENABLED"] = "false"
        try:
            cfg = load_config()
            assert cfg.memory.enabled is False
        finally:
            del os.environ["LINGJI_MEMORY_ENABLED"]

    def test_env_memory_db_path(self):
        os.environ["LINGJI_MEMORY_DB_PATH"] = "/custom/memory/path"
        try:
            cfg = load_config()
            assert cfg.memory.db_path == "/custom/memory/path"
        finally:
            del os.environ["LINGJI_MEMORY_DB_PATH"]
