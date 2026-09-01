"""Fleet 4.0d-3 — bind Job to HITL and decide scheduler vs user (no LLM)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from lingji_agent.execution.approval_scope import (
    ESCALATION_SCHEDULER,
    ESCALATION_USER,
    classify_hitl,
    pick_active_job_for_executor,
)
from lingji_agent.foundation.scheduler import get_scheduler_agent_id
from lingji_agent.network.protocol import Message, MsgType


def _tool_args(payload: dict) -> dict:
    raw = payload.get("tool_args")
    if raw is None:
        raw = payload.get("args")
    return raw if isinstance(raw, dict) else {}


def _active_step_id(job: dict) -> str:
    for st in job.get("steps") or []:
        if not isinstance(st, dict):
            continue
        if (st.get("status") or "") in ("running", "dispatched", "waiting"):
            return str(st.get("step_id") or "")
    return ""


def attach_job_fields(
    job: dict | None,
    tool: str,
    args: dict | None,
    *,
    executor_id: str = "",
) -> dict[str, str]:
    """Fields to merge into HITL_REQ payload."""
    if not job:
        return {
            "escalation": ESCALATION_USER,
            "job_id": "",
            "step_id": "",
            "scheduler_agent_id": get_scheduler_agent_id(fallback_device_id=executor_id),
        }
    scope = job.get("approval_scope") if isinstance(job.get("approval_scope"), dict) else None
    esc = classify_hitl(scope, tool, args)
    sched = (job.get("scheduler_agent_id") or "").strip() or get_scheduler_agent_id(
        fallback_device_id=executor_id
    )
    return {
        "escalation": esc,
        "job_id": str(job.get("job_id") or ""),
        "step_id": _active_step_id(job),
        "scheduler_agent_id": sched,
    }


def decide_delegate(payload: dict, job: dict | None) -> str:
    """approve | escalate_user — scheduler re-check against live Job."""
    if not job:
        return "escalate_user"
    tool = str(payload.get("tool") or "")
    args = _tool_args(payload)
    scope = job.get("approval_scope") if isinstance(job.get("approval_scope"), dict) else None
    if classify_hitl(scope, tool, args) == ESCALATION_SCHEDULER:
        return "approve"
    return "escalate_user"


def pick_job_from_list(jobs: list | None, executor_id: str) -> dict | None:
    return pick_active_job_for_executor(jobs, executor_id)


def user_escalate_payload(original: dict) -> dict[str, Any]:
    """Clone HITL_REQ payload for the user dock."""
    out = dict(original)
    out["escalation"] = ESCALATION_USER
    return out


async def handle_scheduler_hitl_req(
    payload: dict,
    *,
    send: Callable[[Message], Awaitable[None]],
    get_job: Callable[[str], Awaitable[dict]],
    device_id: str,
) -> str:
    """Deterministic delegated HITL. Returns ignore | approved | escalate_user."""
    p = dict(payload or {})
    if (p.get("escalation") or "") != ESCALATION_SCHEDULER:
        return "ignore"
    task_id = (p.get("task_id") or "").strip()
    executor = (p.get("agent_id") or "").strip()
    if not task_id or not executor:
        return "ignore"
    job_id = (p.get("job_id") or "").strip()
    job = None
    if job_id:
        data = await get_job(job_id)
        if isinstance(data, dict) and not data.get("error"):
            job = data
    action = decide_delegate(p, job)
    if action == "approve":
        await send(
            Message(
                msg_type=MsgType.HITL_RES,
                device_id=device_id,
                payload={
                    "task_id": task_id,
                    "decision": "approved",
                    "target_agent_id": executor,
                    "responded_by": "scheduler",
                    "job_id": job_id,
                },
            )
        )
        return "approved"
    user_id = (p.get("target_user_id") or p.get("user_id") or "").strip()
    esc = user_escalate_payload(p)
    if user_id:
        esc["target_user_id"] = user_id
    await send(
        Message(
            msg_type=MsgType.HITL_REQ,
            device_id=device_id,
            payload=esc,
        )
    )
    return "escalate_user"
