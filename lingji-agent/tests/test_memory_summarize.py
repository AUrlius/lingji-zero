"""LLM 记忆总结单元测试 — 三期 3.4"""

from datetime import datetime, timedelta, timezone

import pytest

from lingji_agent.foundation.config import MemoryConfig
from lingji_agent.memory.summarizer import (
    maybe_run_summarization,
    read_last_run,
    run_summarization,
    select_episodes_for_summary,
    should_run_summarization,
    write_last_run,
)
from lingji_agent.memory.vector_store import LocalVectorStore
from tests.test_memory import MockEmbedder


@pytest.fixture
def temp_db_path(tmp_path):
    return str(tmp_path / "memory_db")


@pytest.fixture
def vector_store(temp_db_path):
    return LocalVectorStore(temp_db_path, embedding_function=MockEmbedder())


@pytest.fixture
def now():
    return datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)


def _add_old_episodes(store: LocalVectorStore, count: int, now: datetime) -> None:
    old_ts = (now - timedelta(days=10)).isoformat()
    for i in range(count):
        store.add_memory(
            "episodic",
            f"ep-{i}",
            f"[USER]: message {i}",
            {"timestamp": old_ts, "type": "conversation"},
        )


class MockConnector:
    def __init__(self, content: str = "- user likes python\n- project is Lingji"):
        self.content = content
        self.calls = 0
        self.model_name = "mock"

    async def chat_completion(self, messages, tools=None, stream=False):
        self.calls += 1
        if self.content == "RAISE":
            raise RuntimeError("llm down")
        return {
            "content": self.content,
            "tool_calls": [],
            "usage": {"total_tokens": 42},
        }


class TestShouldRun:
    def test_disabled(self, vector_store, now, temp_db_path):
        cfg = MemoryConfig(
            db_path=temp_db_path,
            summarize_enabled=False,
            summarize_min_episodes=1,
        )
        ok, reason = should_run_summarization(vector_store, cfg, now=now)
        assert not ok
        assert reason == "disabled"

    def test_insufficient_episodes(self, vector_store, now, temp_db_path):
        _add_old_episodes(vector_store, 5, now)
        cfg = MemoryConfig(
            db_path=temp_db_path,
            summarize_min_episodes=30,
            summarize_interval_hours=0,
        )
        ok, reason = should_run_summarization(vector_store, cfg, now=now)
        assert not ok
        assert "episodic_count" in reason

    def test_interval_not_elapsed(self, vector_store, now, temp_db_path):
        _add_old_episodes(vector_store, 35, now)
        write_last_run(temp_db_path, now - timedelta(hours=1))
        cfg = MemoryConfig(
            db_path=temp_db_path,
            summarize_min_episodes=30,
            summarize_interval_hours=24,
        )
        ok, reason = should_run_summarization(vector_store, cfg, now=now)
        assert not ok
        assert "interval" in reason

    def test_cold_start_defer_seeds_last_run(self, vector_store, now, temp_db_path):
        _add_old_episodes(vector_store, 35, now)
        cfg = MemoryConfig(
            db_path=temp_db_path,
            summarize_min_episodes=30,
            summarize_cold_start_defer=True,
        )
        assert read_last_run(temp_db_path) is None
        ok, reason = should_run_summarization(vector_store, cfg, now=now)
        assert not ok
        assert reason == "cold_start_deferred"
        assert read_last_run(temp_db_path) is not None

    def test_cold_start_defer_false_runs_immediately(self, vector_store, now, temp_db_path):
        _add_old_episodes(vector_store, 35, now)
        cfg = MemoryConfig(
            db_path=temp_db_path,
            summarize_min_episodes=30,
            summarize_interval_hours=0,
            summarize_cold_start_defer=False,
        )
        ok, reason = should_run_summarization(vector_store, cfg, now=now)
        assert ok
        assert reason == "ok"


class TestSelectEpisodes:
    def test_selects_oldest_by_age(self, vector_store, now, temp_db_path):
        _add_old_episodes(vector_store, 25, now)
        recent_ts = (now - timedelta(days=1)).isoformat()
        vector_store.add_memory(
            "episodic",
            "recent",
            "[USER]: new",
            {"timestamp": recent_ts, "type": "conversation"},
        )
        cfg = MemoryConfig(db_path=temp_db_path, summarize_batch_size=5, summarize_min_age_days=7)
        batch = select_episodes_for_summary(vector_store, cfg, now=now)
        assert len(batch) == 5
        assert all("ep-" in doc_id for doc_id, _t, _m in batch)


class TestRunSummarization:
    @pytest.mark.asyncio
    async def test_success_deletes_episodic(self, vector_store, now, temp_db_path):
        _add_old_episodes(vector_store, 35, now)
        cfg = MemoryConfig(
            db_path=temp_db_path,
            summarize_min_episodes=30,
            summarize_batch_size=10,
            summarize_interval_hours=0,
            summarize_min_age_days=7,
            summarize_cold_start_defer=False,
        )
        connector = MockConnector()
        before = vector_store.count("episodic")
        result = await run_summarization(vector_store, connector, cfg, now=now)
        assert result.ran
        assert result.deleted_count == 10
        assert result.semantic_id
        assert vector_store.count("episodic") == before - 10
        assert vector_store.count("semantic") == 1
        assert connector.calls == 1
        assert read_last_run(temp_db_path) is not None

    @pytest.mark.asyncio
    async def test_llm_failure_keeps_episodic(self, vector_store, now, temp_db_path):
        _add_old_episodes(vector_store, 35, now)
        cfg = MemoryConfig(
            db_path=temp_db_path,
            summarize_min_episodes=30,
            summarize_interval_hours=0,
            summarize_cold_start_defer=False,
        )
        connector = MockConnector(content="RAISE")
        before = vector_store.count("episodic")
        result = await run_summarization(vector_store, connector, cfg, now=now)
        assert not result.ran
        assert vector_store.count("episodic") == before
        assert vector_store.count("semantic") == 0

    @pytest.mark.asyncio
    async def test_cold_start_defer_skips_llm_then_runs_after_interval(
        self, vector_store, now, temp_db_path
    ):
        _add_old_episodes(vector_store, 35, now)
        cfg = MemoryConfig(
            db_path=temp_db_path,
            summarize_min_episodes=30,
            summarize_batch_size=10,
            summarize_interval_hours=24,
            summarize_min_age_days=7,
            summarize_cold_start_defer=True,
        )
        connector = MockConnector()

        first = await run_summarization(vector_store, connector, cfg, now=now)
        assert not first.ran
        assert first.reason == "cold_start_deferred"
        assert connector.calls == 0
        assert vector_store.count("episodic") == 35

        later = now + timedelta(hours=25)
        result = await run_summarization(vector_store, connector, cfg, now=later)
        assert result.ran
        assert result.deleted_count == 10
        assert connector.calls == 1

    @pytest.mark.asyncio
    async def test_disabled_skips_llm(self, vector_store, now, temp_db_path):
        _add_old_episodes(vector_store, 35, now)
        cfg = MemoryConfig(db_path=temp_db_path, summarize_enabled=False)
        connector = MockConnector()
        result = await maybe_run_summarization(vector_store, connector, cfg)
        assert not result.ran
        assert connector.calls == 0

    @pytest.mark.asyncio
    async def test_no_connector_skips(self, vector_store, temp_db_path):
        cfg = MemoryConfig(db_path=temp_db_path)
        result = await maybe_run_summarization(vector_store, None, cfg)
        assert not result.ran
        assert result.reason == "disabled_or_no_connector"
