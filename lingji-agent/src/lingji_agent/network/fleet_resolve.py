"""Fleet device alias resolution and peer discovery."""

from __future__ import annotations

import os
from typing import Any

import httpx

from lingji_agent.network.file_upload import _gateway_base_url

# Built-in defaults; overridden by config aliases at runtime.
_BUILTIN_AGENT_ALIASES: dict[str, str] = {
    "青铜剑": "lingji-pc",
    "主pc": "lingji-pc",
    "primary pc": "lingji-pc",
    "primarypc": "lingji-pc",
    "空城记": "lingji-laptop",
    "笔记本": "lingji-laptop",
    "laptop": "lingji-laptop",
}


def _norm_key(s: str) -> str:
    return (s or "").strip().lower()


def build_alias_map(
    local_device_id: str,
    local_display_name: str = "",
    local_aliases: list[str] | None = None,
    remote_agents: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Merge built-in, local config, and online agent display names → device_id."""
    m: dict[str, str] = dict(_BUILTIN_AGENT_ALIASES)
    if local_device_id:
        m[_norm_key(local_device_id)] = local_device_id
    if local_display_name:
        m[_norm_key(local_display_name)] = local_device_id
    for alias in local_aliases or []:
        if alias.strip():
            m[_norm_key(alias)] = local_device_id
    for agent in remote_agents or []:
        did = agent.get("device_id") or ""
        if not did:
            continue
        m[_norm_key(did)] = did
        dn = agent.get("display_name") or ""
        if dn:
            m[_norm_key(dn)] = did
    return m


def resolve_agent_id(
    raw: str,
    *,
    local_device_id: str = "",
    local_display_name: str = "",
    local_aliases: list[str] | None = None,
    remote_agents: list[dict[str, Any]] | None = None,
) -> str:
    key = _norm_key(raw)
    if not key:
        return ""
    alias_map = build_alias_map(
        local_device_id, local_display_name, local_aliases, remote_agents,
    )
    if key in alias_map:
        return alias_map[key]
    # Already a lingji-* id
    if raw.strip().startswith("lingji-"):
        return raw.strip()
    return raw.strip()


async def fetch_online_agents(
    *,
    host: str | None = None,
    port: int | None = None,
    auth_token: str | None = None,
) -> list[dict[str, Any]]:
    token = auth_token if auth_token is not None else os.getenv("LINGJI_AUTH_TOKEN", "")
    base = _gateway_base_url(host, port)
    url = f"{base}/v1/agents"
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as session:
            resp = await session.get(url, headers=headers)
            if resp.status_code >= 400:
                return []
            data = resp.json()
            return list(data.get("agents") or [])
    except Exception:
        return []
