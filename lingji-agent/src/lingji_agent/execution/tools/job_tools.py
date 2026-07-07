"""Fleet 4.0a — Job 台账工具（调度 Agent）"""

from __future__ import annotations

from typing import Any

from lingji_agent.execution.registry import RiskLevel, registry
from lingji_agent.network.fleet_resolve import fetch_online_agents, resolve_agent_id
from lingji_agent.network.job_client import create_fleet_file_job, get_job


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
        scheduler_agent_id=sender,
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
