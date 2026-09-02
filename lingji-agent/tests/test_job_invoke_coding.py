"""job_invoke_coding — 秘书派 coding.cursor Job。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from lingji_agent.execution.approval_scope import PLAYBOOK_CODING_CURSOR
from lingji_agent.execution.tools.job_tools import job_invoke, job_invoke_coding


@pytest.mark.asyncio
async def test_job_invoke_rejects_coding_cursor():
    out = await job_invoke(user_id="u1", playbook_id=PLAYBOOK_CODING_CURSOR)
    assert "error" in out
    assert "未知 playbook" in out["error"]


@pytest.mark.asyncio
async def test_brief_required():
    out = await job_invoke_coding(user_id="u1", intent="x", brief="  ")
    assert out == {"error": "brief 不能为空"}


@pytest.mark.asyncio
async def test_runner_only_cursor():
    out = await job_invoke_coding(
        user_id="u1", intent="x", brief="do work", runner="claude"
    )
    assert out == {"error": "runner 只支持 cursor"}


@pytest.mark.asyncio
async def test_timeout_hard_cap():
    out = await job_invoke_coding(
        user_id="u1", intent="x", brief="do work", timeout_sec=3601
    )
    assert out == {"error": "timeout_sec 超过硬顶"}
    out2 = await job_invoke_coding(
        user_id="u1", intent="x", brief="do work", timeout_sec=-1
    )
    assert out2 == {"error": "timeout_sec 超过硬顶"}


@pytest.mark.asyncio
async def test_create_and_dispatch_plan_and_scope():
    create = AsyncMock(
        return_value={"job_id": "LJ-CODE01", "status": "planned", "steps": []}
    )
    dispatch = AsyncMock(
        return_value={
            "job_id": "LJ-CODE01",
            "status": "dispatched",
            "steps": [{"name": "coding_run"}],
        }
    )
    brief = "实现 hello world 并写测试"
    with (
        patch(
            "lingji_agent.execution.tools.job_tools.create_job",
            create,
        ),
        patch(
            "lingji_agent.execution.tools.job_tools.dispatch_job",
            dispatch,
        ),
    ):
        out = await job_invoke_coding(
            user_id="u1",
            intent="",
            brief=brief,
            source_git="https://github.com/AUrlius/lingji-zero.git",
            timeout_sec=0,
        )

    assert out["job_id"] == "LJ-CODE01"
    assert out["status"] == "dispatched"
    assert "已派工 LJ-CODE01（coding.cursor → lingji-pc）" in out["message"]

    create.assert_awaited_once()
    kwargs = create.await_args.kwargs
    assert kwargs["playbook"] == PLAYBOOK_CODING_CURSOR
    assert kwargs["intent"] == brief[:40]
    assert kwargs["plan"]["brief"] == brief
    assert kwargs["plan"]["runner"] == "cursor"
    assert kwargs["plan"]["timeout_sec"] == 1800
    assert kwargs["plan"]["source_git"] == "https://github.com/AUrlius/lingji-zero.git"
    assert kwargs["plan"]["executor_id"] == "lingji-pc"
    assert kwargs["approval_scope"]["playbooks"] == [PLAYBOOK_CODING_CURSOR]
    assert kwargs["approval_scope"]["runners"] == ["cursor"]
    assert kwargs["approval_scope"]["max_timeout_sec"] == 1800
    assert kwargs["approval_scope"]["source_git"] == (
        "https://github.com/AUrlius/lingji-zero.git"
    )

    dispatch.assert_awaited_once_with("LJ-CODE01", executor_id="lingji-pc")
