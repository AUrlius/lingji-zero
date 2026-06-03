"""记忆时间衰减与清理 — Sprint 4 T-4.4（衰减/prune；LLM 总结见 summarizer.py）"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lingji_agent.foundation.config import MemoryConfig
    from lingji_agent.memory.vector_store import LocalVectorStore


def _parse_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except ValueError:
        return None


def compute_age_days(timestamp: str | None, now: datetime | None = None) -> float:
    """记忆距今的天数（浮点）"""
    ts = _parse_timestamp(timestamp)
    if ts is None:
        return 0.0
    ref = now or datetime.now(timezone.utc)
    return max(0.0, (ref - ts).total_seconds() / 86400.0)


def compute_decay_weight(
    timestamp: str | None,
    decay_lambda: float,
    now: datetime | None = None,
) -> float:
    """指数衰减：weight = e^(-λ × age_days)"""
    age_days = compute_age_days(timestamp, now)
    return math.exp(-decay_lambda * age_days)


def apply_decay_ranking(
    candidates: list[dict[str, Any]],
    *,
    decay_enabled: bool,
    decay_lambda: float,
    top_k: int,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """按 relevance_score × decay_weight 重排并截断 top_k"""
    if not candidates:
        return []

    scored: list[dict[str, Any]] = []
    for item in candidates:
        meta = item.get("metadata") or {}
        decay_weight = (
            compute_decay_weight(meta.get("timestamp"), decay_lambda, now)
            if decay_enabled
            else 1.0
        )
        relevance = float(item.get("relevance_score", 0.0))
        final_score = relevance * decay_weight
        scored.append({
            **item,
            "decay_weight": decay_weight,
            "final_score": final_score,
        })

    scored.sort(key=lambda x: x["final_score"], reverse=True)
    return scored[:top_k]


def prune_stale_memories(
    store: LocalVectorStore,
    config: MemoryConfig,
    *,
    now: datetime | None = None,
) -> int:
    """删除衰减权重低于阈值且超过 prune_after_days 的情景记忆"""
    if not config.decay_enabled:
        return 0

    ref = now or datetime.now(timezone.utc)
    to_delete: list[str] = []

    for doc_id, metadata in store.list_episodic_with_metadata():
        age_days = compute_age_days(metadata.get("timestamp"), ref)
        if age_days < config.prune_after_days:
            continue
        weight = compute_decay_weight(metadata.get("timestamp"), config.decay_lambda, ref)
        if weight < config.prune_min_weight:
            to_delete.append(doc_id)

    if to_delete:
        store.delete_by_ids("episodic", to_delete)
    return len(to_delete)
