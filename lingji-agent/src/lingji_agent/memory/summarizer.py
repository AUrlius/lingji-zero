"""LLM 定期记忆总结 — Sprint 4 T-4.4 完整（三期 3.4）"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from lingji_agent.memory.decay import compute_age_days

if TYPE_CHECKING:
    from lingji_agent.cognitive.llm_provider import ILLMConnector
    from lingji_agent.foundation.config import MemoryConfig
    from lingji_agent.memory.vector_store import LocalVectorStore

logger = logging.getLogger(__name__)

_SUMMARIZE_LOCK = asyncio.Lock()
_LAST_RUN_BASENAME = ".summarize_last_run"


@dataclass
class SummarizeResult:
    ran: bool
    deleted_count: int = 0
    semantic_id: str | None = None
    usage_tokens: int = 0
    reason: str = ""


def _last_run_path(db_path: str) -> str:
    return os.path.join(os.path.expanduser(db_path), _LAST_RUN_BASENAME)


def read_last_run(db_path: str) -> datetime | None:
    path = _last_run_path(db_path)
    if not os.path.isfile(path):
        return None
    try:
        raw = open(path, encoding="utf-8").read().strip()
        ts = datetime.fromisoformat(raw)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except (OSError, ValueError):
        return None


def write_last_run(db_path: str, when: datetime | None = None) -> None:
    ref = when or datetime.now(timezone.utc)
    path = _last_run_path(db_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(ref.isoformat())


def _episode_sort_key(item: tuple[str, dict[str, Any]]) -> str:
    _doc_id, meta = item
    return meta.get("timestamp") or ""


def select_episodes_for_summary(
    store: LocalVectorStore,
    config: MemoryConfig,
    *,
    now: datetime | None = None,
) -> list[tuple[str, str, dict[str, Any]]]:
    """选取最旧、满足年龄阈值且未标记 summarized 的 episodic 批次。"""
    ref = now or datetime.now(timezone.utc)
    rows = store.list_episodic_with_metadata()
    eligible: list[tuple[str, str, dict[str, Any]]] = []

    for doc_id, meta in sorted(rows, key=_episode_sort_key):
        if meta.get("summarized"):
            continue
        age = compute_age_days(meta.get("timestamp"), ref)
        if age < config.summarize_min_age_days:
            continue
        text = store.get_document("episodic", doc_id) or ""
        if not text.strip():
            continue
        eligible.append((doc_id, text, meta))
        if len(eligible) >= config.summarize_batch_size:
            break

    return eligible


def build_summary_messages(
    episodes: list[tuple[str, str, dict[str, Any]]],
    max_output_chars: int,
) -> list[dict[str, str]]:
    lines: list[str] = []
    for _doc_id, text, meta in episodes:
        ts = meta.get("timestamp", "")
        lines.append(f"- [{ts}] {text}")

    body = "\n".join(lines)
    return [
        {
            "role": "system",
            "content": (
                "你是记忆提炼助手。从下列情景对话片段中提取可长期复用的语义事实"
                "（用户偏好、项目背景、稳定结论、待办）。"
                "不要编造；只输出 bullet 列表纯文本；"
                f"总长度不超过 {max_output_chars} 字符。"
            ),
        },
        {
            "role": "user",
            "content": f"请总结以下 {len(episodes)} 条旧记忆：\n\n{body}",
        },
    ]


def should_run_summarization(
    store: LocalVectorStore,
    config: MemoryConfig,
    *,
    now: datetime | None = None,
) -> tuple[bool, str]:
    if not config.summarize_enabled:
        return False, "disabled"

    episodic_count = store.count("episodic")
    if episodic_count < config.summarize_min_episodes:
        return False, f"episodic_count={episodic_count}<{config.summarize_min_episodes}"

    last = read_last_run(config.db_path)
    ref = now or datetime.now(timezone.utc)
    if last is None and config.summarize_cold_start_defer:
        write_last_run(config.db_path, ref)
        logger.info(
            "summarize_cold_start_deferred episodic_count=%d",
            episodic_count,
        )
        return False, "cold_start_deferred"

    if last is not None:
        elapsed_h = (ref - last).total_seconds() / 3600.0
        if elapsed_h < config.summarize_interval_hours:
            return False, f"interval={elapsed_h:.1f}h<{config.summarize_interval_hours}h"

    batch = select_episodes_for_summary(store, config, now=ref)
    if not batch:
        return False, "no_eligible_episodes"

    return True, "ok"


async def run_summarization(
    store: LocalVectorStore,
    connector: ILLMConnector,
    config: MemoryConfig,
    *,
    now: datetime | None = None,
) -> SummarizeResult:
    ref = now or datetime.now(timezone.utc)
    ok, reason = should_run_summarization(store, config, now=ref)
    if not ok:
        return SummarizeResult(ran=False, reason=reason)

    episodes = select_episodes_for_summary(store, config, now=ref)
    if not episodes:
        return SummarizeResult(ran=False, reason="no_eligible_episodes")

    messages = build_summary_messages(episodes, config.summarize_max_output_chars)
    try:
        response = await connector.chat_completion(messages, tools=None, stream=False)
    except Exception as exc:
        logger.warning("memory_summarize LLM 失败: %s", exc)
        return SummarizeResult(ran=False, reason=f"llm_error:{exc}")

    summary_text = (response.get("content") or "").strip()
    if not summary_text:
        return SummarizeResult(ran=False, reason="empty_summary")

    if len(summary_text) > config.summarize_max_output_chars:
        summary_text = summary_text[: config.summarize_max_output_chars]

    semantic_id = f"summary_{uuid.uuid4().hex[:12]}"
    doc_text = f"Memory Summary ({len(episodes)} episodes):\n{summary_text}"
    store.add_memory(
        "semantic",
        semantic_id,
        doc_text,
        {
            "type": "summary",
            "source_count": len(episodes),
            "timestamp": ref.isoformat(),
        },
    )

    ids_to_delete = [doc_id for doc_id, _text, _meta in episodes]
    store.delete_by_ids("episodic", ids_to_delete)
    write_last_run(config.db_path, ref)

    usage = response.get("usage") or {}
    usage_tokens = int(usage.get("total_tokens") or 0)
    logger.info(
        "summarize_complete deleted=%d semantic_id=%s usage_tokens=%d",
        len(ids_to_delete),
        semantic_id,
        usage_tokens,
    )
    return SummarizeResult(
        ran=True,
        deleted_count=len(ids_to_delete),
        semantic_id=semantic_id,
        usage_tokens=usage_tokens,
        reason="ok",
    )


async def maybe_run_summarization(
    store: LocalVectorStore,
    connector: ILLMConnector | None,
    config: MemoryConfig,
) -> SummarizeResult:
    if not config.summarize_enabled or connector is None:
        return SummarizeResult(ran=False, reason="disabled_or_no_connector")

    async with _SUMMARIZE_LOCK:
        return await run_summarization(store, connector, config)
