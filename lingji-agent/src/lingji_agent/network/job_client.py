"""Fleet 4.0a — Gateway Job API client"""

from __future__ import annotations

import os

import httpx

from lingji_agent.network.file_upload import _gateway_base_url


async def create_fleet_file_job(
    *,
    user_id: str,
    sender_agent_id: str,
    receiver_agent_id: str,
    file_hint: str = "",
    intent: str = "",
    scheduler_agent_id: str = "",
    sender_display_name: str = "",
    receiver_display_name: str = "",
    host: str | None = None,
    port: int | None = None,
    auth_token: str | None = None,
) -> dict:
    """POST /v1/jobs — playbook fleet.file_transfer"""
    if not user_id:
        return {"error": "user_id 不能为空"}
    token = auth_token if auth_token is not None else os.getenv("LINGJI_AUTH_TOKEN", "")
    base = _gateway_base_url(host, port)
    url = f"{base}/v1/jobs"
    body = {
        "user_id": user_id,
        "scheduler_agent_id": scheduler_agent_id or sender_agent_id,
        "intent": intent or f"Fleet 传文件 {sender_agent_id} → {receiver_agent_id}",
        "playbook": "fleet.file_transfer",
        "plan": {
            "sender_agent_id": sender_agent_id,
            "receiver_agent_id": receiver_agent_id,
            "file_hint": file_hint,
            "sender_display_name": sender_display_name,
            "receiver_display_name": receiver_display_name,
        },
    }
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as session:
            resp = await session.post(url, json=body, headers=headers)
            if resp.status_code >= 400:
                return {"error": f"create job 失败 ({resp.status_code}): {resp.text[:200]}"}
            return resp.json()
    except Exception as e:
        return {"error": f"create job 请求失败: {e}"}


async def get_job(
    job_id: str,
    *,
    host: str | None = None,
    port: int | None = None,
    auth_token: str | None = None,
) -> dict:
    """GET /v1/jobs/{job_id}"""
    jid = (job_id or "").strip()
    if not jid:
        return {"error": "job_id 不能为空"}
    token = auth_token if auth_token is not None else os.getenv("LINGJI_AUTH_TOKEN", "")
    base = _gateway_base_url(host, port)
    url = f"{base}/v1/jobs/{jid}"
    if token:
        url += f"?token={token}"
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as session:
            resp = await session.get(url, headers=headers)
            if resp.status_code >= 400:
                return {"error": f"get job 失败 ({resp.status_code}): {resp.text[:200]}"}
            return resp.json()
    except Exception as e:
        return {"error": f"get job 请求失败: {e}"}
