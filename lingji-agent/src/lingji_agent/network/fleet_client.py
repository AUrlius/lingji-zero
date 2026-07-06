"""Fleet Phase 3 — Gateway 跨 Agent 文件中转客户端"""

from __future__ import annotations

import os

import httpx

from lingji_agent.network.file_upload import _gateway_base_url


async def request_fleet_transfer(
    *,
    from_agent_id: str,
    to_agent_id: str = "",
    to_user_id: str = "",
    thread_id: str = "",
    user_id: str = "",
    uploads: list[dict],
    host: str | None = None,
    port: int | None = None,
    auth_token: str | None = None,
) -> dict:
    """POST /v1/fleet/transfer 发起跨箱文件中继。"""
    if not uploads:
        return {"error": "uploads 不能为空"}
    if bool(to_agent_id) == bool(to_user_id):
        return {"error": "必须指定 to_agent_id 或 to_user_id 之一"}

    token = auth_token if auth_token is not None else os.getenv("LINGJI_AUTH_TOKEN", "")
    base = _gateway_base_url(host, port)
    url = f"{base}/v1/fleet/transfer"
    body = {
        "from_agent_id": from_agent_id,
        "to_agent_id": to_agent_id,
        "to_user_id": to_user_id,
        "thread_id": thread_id,
        "user_id": user_id or to_user_id,
        "uploads": uploads,
    }
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=120.0) as session:
            resp = await session.post(url, json=body, headers=headers)
            if resp.status_code >= 400:
                return {
                    "error": f"Fleet transfer 失败 ({resp.status_code}): {resp.text[:200]}",
                }
            return resp.json()
    except Exception as e:
        return {"error": f"Fleet transfer 请求失败: {e}"}
