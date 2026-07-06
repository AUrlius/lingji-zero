"""Gateway Lingji file ID (LF-ID) registry client."""

from __future__ import annotations

import os
from typing import Any

import httpx

from lingji_agent.network.file_upload import _gateway_base_url


async def register_lingji_file(
    *,
    user_id: str,
    name: str,
    holder_agent_id: str,
    local_path: str = "",
    size_bytes: int = 0,
    mime: str = "application/octet-stream",
    gateway_file_id: str = "",
    source_agent_id: str = "",
    lingji_file_id: str = "",
    host: str | None = None,
    port: int | None = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    token = auth_token if auth_token is not None else os.getenv("LINGJI_AUTH_TOKEN", "")
    base = _gateway_base_url(host, port)
    url = f"{base}/v1/files/registry"
    body = {
        "user_id": user_id,
        "name": name,
        "holder_agent_id": holder_agent_id,
        "local_path": local_path,
        "size_bytes": size_bytes,
        "mime": mime,
        "gateway_file_id": gateway_file_id,
        "source_agent_id": source_agent_id,
    }
    if lingji_file_id:
        body["lingji_file_id"] = lingji_file_id
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as session:
            resp = await session.post(url, json=body, headers=headers)
            if resp.status_code >= 400:
                return {"error": f"registry 失败 ({resp.status_code}): {resp.text[:200]}"}
            return resp.json()
    except Exception as e:
        return {"error": f"registry 请求失败: {e}"}


async def request_fleet_relay(
    *,
    lingji_file_id: str,
    user_id: str,
    from_agent_id: str,
    to_agent_id: str = "",
    to_user_id: str = "",
    thread_id: str = "",
    host: str | None = None,
    port: int | None = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    token = auth_token if auth_token is not None else os.getenv("LINGJI_AUTH_TOKEN", "")
    base = _gateway_base_url(host, port)
    url = f"{base}/v1/fleet/relay"
    body = {
        "lingji_file_id": lingji_file_id,
        "user_id": user_id,
        "from_agent_id": from_agent_id,
        "to_agent_id": to_agent_id,
        "to_user_id": to_user_id,
        "thread_id": thread_id,
    }
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=120.0) as session:
            resp = await session.post(url, json=body, headers=headers)
            if resp.status_code >= 400:
                return {"error": f"fleet relay 失败 ({resp.status_code}): {resp.text[:200]}"}
            return resp.json()
    except Exception as e:
        return {"error": f"fleet relay 请求失败: {e}"}
