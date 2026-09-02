"""Fleet 4.0a — Job 台账工具（调度 Agent）"""

from __future__ import annotations

from typing import Any

from lingji_agent.execution.registry import RiskLevel, registry
from lingji_agent.foundation.scheduler import get_scheduler_agent_id
from lingji_agent.network.fleet_resolve import fetch_online_agents, resolve_agent_id
from lingji_agent.network.job_client import create_fleet_file_job, create_job, dispatch_job, get_job


def _local_agent_id() -> str:
    import os
    return os.getenv("LINGJI_DEVICE_ID", "lingji-pc")


def _local_display_name() -> str:
    import os
    return os.getenv("LINGJI_DISPLAY_NAME", "")


async def _resolve_agent(raw: str) -> str:
    agents = await fetch_online_agents()
    return resolve_agent_id(
        raw,
        local_device_id=_local_agent_id(),
        local_display_name=_local_display_name(),
        local_aliases=[],
        remote_agents=agents,
    )


def format_job_close_message(job: dict) -> str:
    """用户可见结案句（一级 LJ-*）。"""
    job_id = job.get("job_id", "")
    status = job.get("status", "")
    summary = (job.get("summary") or "").strip()
    if summary:
        return summary
    if status == "completed":
        return f"{job_id} 已完成。"
    if status == "failed":
        return f"{job_id} 失败。"
    return f"{job_id} 状态：{status or 'unknown'}"


@registry.register(
    name="job_get",
    description="查询 Fleet Job 台账（LJ-*）状态与二级步骤。用户问「任务进度/刚才那个任务」时使用。",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "一级任务 ID，如 LJ-A1B2C3D4"},
        },
        "required": ["job_id"],
    },
    risk=RiskLevel.SAFE,
)
async def job_get(job_id: str = "") -> dict:
    data = await get_job(job_id)
    if data.get("error"):
        return data
    return {
        "job_id": data.get("job_id"),
        "status": data.get("status"),
        "summary": data.get("summary"),
        "steps": data.get("steps"),
        "message": format_job_close_message(data),
    }


@registry.register(
    name="job_create_fleet_transfer",
    description=(
        "创建跨设备传文件 Job（LJ-*），供后续 fleet_send_file 关联。"
        "一般无需单独调用；fleet_send_file 会自动创建。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "to_agent_id": {"type": "string"},
            "file_hint": {"type": "string"},
            "intent": {"type": "string"},
        },
        "required": ["user_id", "to_agent_id"],
    },
    risk=RiskLevel.SAFE,
)
async def job_create_fleet_transfer(
    user_id: str = "",
    to_agent_id: str = "",
    file_hint: str = "",
    intent: str = "",
) -> dict:
    sender = _local_agent_id()
    receiver = await _resolve_agent(to_agent_id)
    if not receiver:
        return {"error": f"无法解析目标 Agent: {to_agent_id}"}
    job = await create_fleet_file_job(
        user_id=user_id,
        sender_agent_id=sender,
        receiver_agent_id=receiver,
        file_hint=file_hint,
        intent=intent,
        scheduler_agent_id=get_scheduler_agent_id(fallback_device_id=sender),
        sender_display_name=_local_display_name(),
    )
    if job.get("error"):
        return job
    return {
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "steps": job.get("steps"),
        "message": f"已创建任务 {job.get('job_id')}（{sender} → {receiver}）",
    }


@registry.register(
    name="job_invoke",
    description=(
        "秘书派工：创建 LJ-* 并委派值守机执行固定 playbook。"
        "playbook_id: agent.status | agent.restart | git-pull-deploy | fleet-smoke。"
        "用户要检查上海 Agent、重启青铜剑 Agent 时必须用此工具，禁止 execute_command。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "playbook_id": {
                "type": "string",
                "description": "agent.status / agent.restart / git-pull-deploy / fleet-smoke",
            },
            "intent": {"type": "string"},
            "executor_id": {"type": "string", "description": "默认 lingji-pc"},
        },
        "required": ["user_id", "playbook_id"],
    },
    risk=RiskLevel.SAFE,
)
async def job_invoke(
    user_id: str = "",
    playbook_id: str = "",
    intent: str = "",
    executor_id: str = "",
) -> dict:
    from lingji_agent.execution.approval_scope import default_scope
    from lingji_agent.execution.playbook_runner import PLAYBOOK_SCRIPTS

    pb = (playbook_id or "").strip()
    if pb not in PLAYBOOK_SCRIPTS:
        return {"error": f"未知 playbook: {pb}，可选: {', '.join(PLAYBOOK_SCRIPTS)}"}
    executor = (executor_id or "lingji-pc").strip()
    job = await create_job(
        user_id=user_id,
        playbook=pb,
        intent=intent or pb,
        plan={"executor_id": executor},
        approval_scope=default_scope(pb),
        scheduler_agent_id=get_scheduler_agent_id(fallback_device_id=_local_agent_id()),
    )
    if job.get("error"):
        return job
    dispatched = await dispatch_job(
        job.get("job_id", ""),
        executor_id=executor,
    )
    if dispatched.get("error"):
        return {
            "job_id": job.get("job_id"),
            "error": dispatched.get("error"),
            "message": f"已创建 {job.get('job_id')} 但派工失败",
        }
    return {
        "job_id": dispatched.get("job_id") or job.get("job_id"),
        "status": dispatched.get("status"),
        "steps": dispatched.get("steps"),
        "message": format_job_close_message(dispatched)
        if dispatched.get("status") in ("completed", "failed")
        else f"已派工 {dispatched.get('job_id')}（{pb} → {executor}），进度见办公桌工单卡。",
    }


@registry.register(
    name="job_invoke_coding",
    description=(
        "秘书派编码任务：创建 LJ-*（playbook=coding.cursor）并委派值守机拉起无头 Cursor。"
        "用户要改仓库/写代码时必须用此工具，禁止 execute_command / 禁止走 job_invoke。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "intent": {"type": "string", "description": "工单卡标题，短；空则用 brief 前 40 字"},
            "brief": {"type": "string", "description": "任务说明书"},
            "executor_id": {"type": "string", "description": "默认 lingji-pc"},
            "runner": {"type": "string", "description": "默认 cursor；本切片只支持 cursor"},
            "source_git": {"type": "string", "description": "空或 git URL；执行机再查白名单"},
            "timeout_sec": {
                "type": "integer",
                "description": "默认 14400；0 同默认；硬顶 28800",
            },
        },
        "required": ["user_id", "intent", "brief"],
    },
    risk=RiskLevel.SAFE,
)
async def job_invoke_coding(
    user_id: str = "",
    intent: str = "",
    brief: str = "",
    executor_id: str = "",
    runner: str = "cursor",
    source_git: str = "",
    timeout_sec: int = 0,
) -> dict:
    from lingji_agent.execution.approval_scope import (
        PLAYBOOK_CODING_CURSOR,
        default_coding_scope,
    )

    brief_text = (brief or "").strip()
    if not brief_text:
        return {"error": "brief 不能为空"}
    runner_id = (runner or "cursor").strip() or "cursor"
    if runner_id != "cursor":
        return {"error": "runner 只支持 cursor"}

    try:
        timeout = int(timeout_sec or 0)
    except (TypeError, ValueError):
        return {"error": "timeout_sec 超过硬顶"}
    if timeout == 0:
        timeout = 14400
    if timeout < 1 or timeout > 28800:
        return {"error": "timeout_sec 超过硬顶"}

    intent_text = (intent or "").strip() or brief_text[:40]
    executor = (executor_id or "lingji-pc").strip() or "lingji-pc"
    plan = {
        "executor_id": executor,
        "runner": runner_id,
        "brief": brief_text,
        "source_git": source_git or "",
        "timeout_sec": timeout,
    }
    job = await create_job(
        user_id=user_id,
        playbook=PLAYBOOK_CODING_CURSOR,
        intent=intent_text,
        plan=plan,
        approval_scope=default_coding_scope(
            timeout_sec=timeout,
            source_git=source_git or "",
            runner=runner_id,
        ),
        scheduler_agent_id=get_scheduler_agent_id(fallback_device_id=_local_agent_id()),
    )
    if job.get("error"):
        return job
    dispatched = await dispatch_job(
        job.get("job_id", ""),
        executor_id=executor,
    )
    if dispatched.get("error"):
        return {
            "job_id": job.get("job_id"),
            "error": dispatched.get("error"),
            "message": f"已创建 {job.get('job_id')} 但派工失败",
        }
    return {
        "job_id": dispatched.get("job_id") or job.get("job_id"),
        "status": dispatched.get("status"),
        "steps": dispatched.get("steps"),
        "message": format_job_close_message(dispatched)
        if dispatched.get("status") in ("completed", "failed")
        else (
            f"已派工 {dispatched.get('job_id')}（{PLAYBOOK_CODING_CURSOR} → {executor}），"
            "进度见办公桌工单卡。"
        ),
    }
