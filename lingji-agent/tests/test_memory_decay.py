"""记忆时间衰减单元测试 — Sprint 4 T-4.4"""

from datetime import datetime, timedelta, timezone

import pytest

from lingji_agent.memory.decay import (
    apply_decay_ranking,
    compute_age_days,
    compute_decay_weight,
    prune_stale_memories,
)
from lingji_agent.foundation.config import MemoryConfig


class TestDecayMath:
    def test_fresh_memory_weight_near_one(self):
        now = datetime(2026, 6, 2, tzinfo=timezone.utc)
        ts = (now - timedelta(hours=1)).isoformat()
        weight = compute_decay_weight(ts, decay_lambda=0.01, now=now)
        assert weight > 0.99

    def test_old_memory_weight_lower(self):
        now = datetime(2026, 6, 2, tzinfo=timezone.utc)
        fresh = (now - timedelta(days=1)).isoformat()
        old = (now - timedelta(days=60)).isoformat()
        assert compute_decay_weight(old, 0.01, now) < compute_decay_weight(fresh, 0.01, now)

    def test_age_days(self):
        now = datetime(2026, 6, 2, tzinfo=timezone.utc)
        ts = (now - timedelta(days=10)).isoformat()
        assert compute_age_days(ts, now) == pytest.approx(10.0, abs=0.01)


class TestDecayRanking:
    def test_newer_episode_ranks_higher(self):
        now = datetime(2026, 6, 2, tzinfo=timezone.utc)
        candidates = [
            {
                "content": "old",
                "metadata": {"timestamp": (now - timedelta(days=90)).isoformat()},
                "relevance_score": 0.9,
            },
            {
                "content": "new",
                "metadata": {"timestamp": (now - timedelta(days=1)).isoformat()},
                "relevance_score": 0.9,
            },
        ]
        ranked = apply_decay_ranking(
            candidates,
            decay_enabled=True,
            decay_lambda=0.01,
            top_k=2,
            now=now,
        )
        assert ranked[0]["content"] == "new"
        assert ranked[0]["final_score"] > ranked[1]["final_score"]

    def test_decay_disabled_preserves_order(self):
        candidates = [
            {"content": "a", "metadata": {}, "relevance_score": 0.5},
            {"content": "b", "metadata": {}, "relevance_score": 0.9},
        ]
        ranked = apply_decay_ranking(
            candidates,
            decay_enabled=False,
            decay_lambda=0.01,
            top_k=2,
        )
        assert ranked[0]["content"] == "b"


class TestPruneStale:
    def test_prune_deletes_old_low_weight(self):
        class FakeStore:
            def __init__(self):
                now = datetime(2026, 6, 2, tzinfo=timezone.utc)
                self._rows = [
                    ("keep", {"timestamp": (now - timedelta(days=5)).isoformat()}),
                    ("drop", {"timestamp": (now - timedelta(days=365)).isoformat()}),
                ]
                self.deleted = []

            def list_episodic_with_metadata(self):
                return list(self._rows)

            def delete_by_ids(self, collection, ids):
                self.deleted.extend(ids)

        store = FakeStore()
        cfg = MemoryConfig(decay_enabled=True, prune_after_days=30, prune_min_weight=0.05)
        removed = prune_stale_memories(store, cfg, now=datetime(2026, 6, 2, tzinfo=timezone.utc))
        assert removed == 1
        assert store.deleted == ["drop"]
