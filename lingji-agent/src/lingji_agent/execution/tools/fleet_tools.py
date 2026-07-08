"""Fleet Phase 3 — 跨 Agent 文件推送与 LF-ID 中继工具"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from lingji_agent.execution.registry import RiskLevel, registry
from lingji_agent.execution.tools.file_tools import (
    _is_sensitive_path,
    _prepare_upload_path,
    _resolve_candidates,
)
from lingji_agent.network.file_registry_client import register_lingji_file, request_fleet_relay
from lingji_agent.network.file_upload import DEFAULT_MAX_BYTES, upload_file_to_gateway
from lingji_agent.network.fleet_client import request_fleet_transfer
from lingji_agent.network.fleet_resolve import fetch_online_agents, resolve_agent_id
from lingji_agent.foundation.scheduler import get_scheduler_agent_id
from lingji_agent.network.job_client import create_fleet_file_job


def _local_agent_id() -> str:
    return os.getenv("LINGJI_DEVICE_ID", "lingji-pc")


def _local_display_name() -> str:
    return os.getenv("LINGJI_DISPLAY_NAME", "")


def _local_aliases() -> list[str]:
    raw = os.getenv("LINGJI_AGENT_ALIASES", "")
    if not raw:
        return []
    return [a.strip() for a in raw.split(",") if a.strip()]


async def _resolve_to_agent(raw: str) -> str:
    agents = await fetch_online_agents()
    return resolve_agent_id(
        raw,
        local_device_id=_local_agent_id(),
        local_display_name=_local_display_name(),
        local_aliases=_local_aliases(),
        remote_agents=agents,
    )


async def _display_name_for(agent_id: str) -> str:
    agents = await fetch_online_agents()
    for a in agents:
        if a.get("device_id") == agent_id:
            return a.get("display_name") or agent_id
    if agent_id == _local_agent_id():
        return _local_display_name() or agent_id
    return agent_id


async def _upload_and_attachment(path: Path, display_name: str | None = None) -> dict:
    upload_result = await upload_file_to_gateway(path)
    if upload_result.get("error"):
        return upload_result
    name = display_name or upload_result.get("name", path.name)
    attachment = {
        "file_id": upload_result.get("file_id", ""),
        "name": name,
        "size_bytes": upload_result.get("size_bytes", 0),
        "mime": upload_result.get("mime", "application/octet-stream"),
        "download_path": upload_result.get("download_path", ""),
    }
    if not attachment["download_path"]:
        return {"error": "Gateway 未返回 download_path", "raw": upload_result}
    return {"attachment": attachment, "upload": upload_result}


@registry.register(
    name="fleet_send_file",
    description=(
        "跨设备传文件：将本机文件经 Gateway 中继到另一台 Agent 的 incoming_dir，"
        "或推送到用户手机/Web。"
        "用户说「发到 PC/青铜剑/另一台/空城记」时用此工具；"
        "已有 LF-ID 时用 lingji_file_id 参数调用 relay_file_by_id。"
        "本机直接推手机用 send_file_to_user。禁止 curl/wget。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "文件名关键词"},
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "精确文件路径",
            },
            "to_agent_id": {"type": "string", "description": "目标 Agent ID 或展示名/别名"},
            "to_user_id": {"type": "string", "description": "目标 user_id"},
            "thread_id": {"type": "string"},
            "user_id": {"type": "string"},
        },
    },
    risk=RiskLevel.WARN,
)
async def fleet_send_file(
    query: str = "",
    paths: list[str] | None = None,
    to_agent_id: str = "",
    to_user_id: str = "",
    thread_id: str = "",
    user_id: str = "",
) -> dict:
    to_agent = await _resolve_to_agent(to_agent_id) if to_agent_id else ""
    to_user = (to_user_id or "").strip()
    if bool(to_agent) == bool(to_user):
        return {"error": "请指定 to_agent_id（另一台 PC）或 to_user_id（手机/Web）之一"}

    candidates, err = _resolve_candidates(query, paths)
    if err:
        return {"error": err}

    for p in candidates:
        if _is_sensitive_path(p):
            return {
                "error": f"文件「{p.name}」可能含敏感内容，需在任意已登录设备点击批准按钮后再发送",
                "sensitive": True,
                "path": str(p),
            }

    upload_path, display_name, cleanup = _prepare_upload_path(candidates)
    if upload_path is None:
        return {
            "error": "多个文件不在同一目录，请分别发送或指定单个 paths",
            "candidates": [str(p) for p in candidates],
        }

    try:
        up = await _upload_and_attachment(upload_path, display_name)
    finally:
        if cleanup and cleanup.exists():
            cleanup.unlink(missing_ok=True)

    if up.get("error"):
        return up
    attachment = up["attachment"]
    from_agent = _local_agent_id()

    reg = await register_lingji_file(
        user_id=user_id or to_user,
        name=attachment["name"],
        holder_agent_id=from_agent,
        local_path=str(upload_path) if upload_path.exists() else "",
        size_bytes=attachment.get("size_bytes", 0),
        mime=attachment.get("mime", ""),
        gateway_file_id=attachment.get("file_id", ""),
        source_agent_id=from_agent,
    )
    lf_id = reg.get("lingji_file_id", "")
    lingji_files = [{"lingji_file_id": lf_id, "name": attachment["name"]}] if lf_id else []

    fleet_job_id = ""
    effective_user = user_id or to_user
    if to_agent and effective_user:
        job = await create_fleet_file_job(
            user_id=effective_user,
            sender_agent_id=from_agent,
            receiver_agent_id=to_agent,
            file_hint=attachment.get("name", ""),
            intent=f"传文件 {attachment.get('name', '')} → {to_agent}",
            scheduler_agent_id=get_scheduler_agent_id(fallback_device_id=from_agent),
            sender_display_name=await _display_name_for(from_agent),
            receiver_display_name=await _display_name_for(to_agent),
        )
        if job.get("error"):
            return job
        fleet_job_id = job.get("job_id", "")

    transfer = await request_fleet_transfer(
        from_agent_id=from_agent,
        to_agent_id=to_agent,
        to_user_id=to_user,
        thread_id=thread_id,
        user_id=effective_user,
        uploads=[attachment],
        job_id=fleet_job_id,
    )
    if transfer.get("error"):
        return transfer

    dest = to_agent or to_user
    status = transfer.get("status", "pending")
    transfer_id = transfer.get("transfer_id", "")
    msg = (
        f"已发起跨箱传输「{attachment['name']}」→ {dest}"
        f"（{status}，transfer_id={transfer_id}）"
    )
    if fleet_job_id:
        msg = (
            f"{fleet_job_id} 已发起。"
            f"传输「{attachment['name']}」→ {dest}（{status}）。"
            f"接收确认后将自动推送结案消息。"
        )
    if lf_id:
        msg += f"\n📎 灵机文件 ID：{lf_id}"
    out: dict[str, Any] = {
        "message": msg,
        "status": status,
        "transfer_id": transfer_id,
        "job_id": fleet_job_id or transfer.get("job_id", ""),
        "to_agent_id": to_agent,
        "lingji_file_id": lf_id,
        "lingji_files": lingji_files,
        "max_bytes": DEFAULT_MAX_BYTES,
    }
    if to_user:
        out["attachments"] = [attachment]
    return out


@registry.register(
    name="relay_file_by_id",
    description=(
        "按灵机文件 ID（LF-xxx）跨设备转发文件。"
        "用户说「把 LF-xxx 发给青铜剑/发给我」时使用。"
        "由当前持有文件的 Agent 读盘并走传输管道。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "lingji_file_id": {
                "type": "string",
                "description": "灵机文件 ID，如 LF-8A3F2C1D",
            },
            "to_agent_id": {"type": "string", "description": "目标 Agent"},
            "to_user_id": {"type": "string", "description": "目标 user_id"},
            "thread_id": {"type": "string"},
            "user_id": {"type": "string"},
        },
        "required": ["lingji_file_id"],
    },
    risk=RiskLevel.WARN,
)
async def relay_file_by_id(
    lingji_file_id: str = "",
    to_agent_id: str = "",
    to_user_id: str = "",
    thread_id: str = "",
    user_id: str = "",
) -> dict:
    lf_id = (lingji_file_id or "").strip().upper()
    if not lf_id.startswith("LF-"):
        return {"error": "请提供有效的 lingji_file_id（LF- 开头）"}
    to_agent = await _resolve_to_agent(to_agent_id) if to_agent_id else ""
    to_user = (to_user_id or "").strip()
    if bool(to_agent) == bool(to_user):
        return {"error": "请指定 to_agent_id 或 to_user_id 之一"}
    if not user_id and not to_user:
        return {"error": "缺少 user_id"}

    relay = await request_fleet_relay(
        lingji_file_id=lf_id,
        user_id=user_id or to_user,
        from_agent_id=_local_agent_id(),
        to_agent_id=to_agent,
        to_user_id=to_user,
        thread_id=thread_id,
    )
    if relay.get("error"):
        return relay
    dest = to_agent or to_user
    return {
        "message": f"已请求转发 {lf_id} → {dest}（{relay.get('status', 'pending')}）",
        "lingji_file_id": lf_id,
        "status": relay.get("status"),
        "holder_agent_id": relay.get("holder_agent_id"),
    }
