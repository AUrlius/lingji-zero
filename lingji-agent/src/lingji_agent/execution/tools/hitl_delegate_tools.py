"""Fleet 4.0d-3 — scheduler HITL list/respond (fallback; main path is HITL_REQ handler)."""

from __future__ import annotations

import os

import httpx

from lingji_agent.execution.registry import RiskLevel, registry
from lingji_agent.network.file_upload import _gateway_base_url


def _token() -> str:
    return os.getenv("LINGJI_AUTH_TOKEN", "")


def _headers(token: str) -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


@registry.register(
    name="hitl_list_pending",
    description="列出调度代批队列中的 HITL（escalation=scheduler）。主路径由系统自动代批，一般无需调用。",
    parameters={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "job_id": {"type": "string"},
        },
        "required": ["user_id"],
    },
    risk=RiskLevel.SAFE,
)
async def hitl_list_pending(user_id: str = "", job_id: str = "") -> dict:
    uid = (user_id or "").strip()
    if not uid:
        return {"error": "user_id 不能为空", "pending": []}
    token = _token()
    url = (
        f"{_gateway_base_url()}/v1/hitl/pending?user_id={uid}"
        f"&escalation=scheduler"
    )
    if token:
        url += f"&token={token}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as session:
            resp = await session.get(url, headers=_headers(token))
            if resp.status_code >= 400:
                return {"error": f"list hitl 失败 ({resp.status_code})", "pending": []}
            data = resp.json()
    except Exception as e:
        return {"error": str(e), "pending": []}
    items = data.get("pending") if isinstance(data, dict) else []
    if not isinstance(items, list):
        items = []
    jid = (job_id or "").strip()
    if jid:
        items = [x for x in items if isinstance(x, dict) and x.get("job_id") == jid]
    return {"pending": items, "count": len(items)}


@registry.register(
    name="hitl_delegate_respond",
    description="调度代批或拒绝一条 HITL。范围内系统会自动批准；此工具仅兜底。",
    parameters={
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "decision": {"type": "string", "description": "approved 或 rejected"},
            "target_agent_id": {"type": "string", "description": "执行机 device_id"},
            "reason": {"type": "string"},
        },
        "required": ["task_id", "decision", "target_agent_id"],
    },
    risk=RiskLevel.SAFE,
)
async def hitl_delegate_respond(
    task_id: str = "",
    decision: str = "",
    target_agent_id: str = "",
    reason: str = "",
) -> dict:
    tid = (task_id or "").strip()
    dec = (decision or "").strip()
    agent = (target_agent_id or "").strip()
    if not tid or dec not in ("approved", "rejected") or not agent:
        return {"error": "需要 task_id、decision=approved|rejected、target_agent_id"}
    token = _token()
    url = f"{_gateway_base_url()}/v1/hitl/respond"
    if token:
        url += f"?token={token}"
    body = {
        "task_id": tid,
        "decision": dec,
        "target_agent_id": agent,
        "responded_by": "scheduler",
        "reason": reason or "",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as session:
            resp = await session.post(url, json=body, headers=_headers(token))
            if resp.status_code >= 400:
                return {"error": f"respond 失败 ({resp.status_code}): {resp.text[:200]}"}
            return {"status": "ok", "task_id": tid, "decision": dec, **(resp.json() if resp.content else {})}
    except Exception as e:
        return {"error": str(e)}
