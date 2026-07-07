"""Agent 活动状态指示 — activity payload 与 reporter 回调"""

import pytest

from lingji_agent.cognitive.orchestrator import _notify_activity, build_run_config


@pytest.mark.asyncio
async def test_notify_activity_calls_async_reporter():
    calls = []

    async def reporter(phase: str, detail: str = "") -> None:
        calls.append((phase, detail))

    await _notify_activity({"_activity_reporter": reporter}, "tool", "read_file")
    assert calls == [("tool", "read_file")]


def test_build_run_config_includes_activity_reporter():
    async def reporter(phase, detail=""):
        pass

    cfg = build_run_config("thread-1", user_id="user-1", activity_reporter=reporter)
    assert cfg["configurable"]["_activity_reporter"] is reporter
