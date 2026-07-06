"""Fleet Phase 3 — 跨 Agent 文件推送工具"""

from __future__ import annotations

import os

from lingji_agent.execution.registry import RiskLevel, registry
from lingji_agent.execution.tools.file_tools import (
    _is_sensitive_path,
    _prepare_upload_path,
    _resolve_candidates,
)
from lingji_agent.network.file_upload import DEFAULT_MAX_BYTES, upload_file_to_gateway
from lingji_agent.network.fleet_client import request_fleet_transfer


def _local_agent_id() -> str:
    return os.getenv("LINGJI_DEVICE_ID", "lingji-pc")


@registry.register(
    name="fleet_send_file",
    description=(
        "跨设备传文件：将本机文件经 Gateway 中继到另一台 Agent 的 incoming_dir，"
        "或推送到用户手机/Web 下载。"
        "用户说「发到 PC/青铜剑/另一台/空城记」时用此工具；"
        "本机直接推手机用 send_file_to_user。禁止 curl/wget。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "文件名关键词或描述",
            },
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可选：精确文件路径",
            },
            "to_agent_id": {
                "type": "string",
                "description": "目标 Agent，如 lingji-pc、lingji-laptop",
            },
            "to_user_id": {
                "type": "string",
                "description": "目标用户 user-xxxxxxxx（发到手机/Web 时用）",
            },
            "thread_id": {
                "type": "string",
                "description": "会话 thread_id（由系统注入，可留空）",
            },
            "user_id": {
                "type": "string",
                "description": "发起用户 user_id（由系统注入，可留空）",
            },
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
    """读盘 → 上传 Gateway /files → POST /v1/fleet/transfer。"""
    to_agent = (to_agent_id or "").strip()
    to_user = (to_user_id or "").strip()
    if bool(to_agent) == bool(to_user):
        return {"error": "请指定 to_agent_id（另一台 PC）或 to_user_id（手机/Web）之一"}

    candidates, err = _resolve_candidates(query, paths)
    if err:
        return {"error": err}

    for p in candidates:
        if _is_sensitive_path(p):
            return {
                "error": f"文件「{p.name}」可能含敏感内容，需用户在手机端确认后再发送",
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
        upload_result = await upload_file_to_gateway(upload_path)
    finally:
        if cleanup and cleanup.exists():
            cleanup.unlink(missing_ok=True)

    if upload_result.get("error"):
        return upload_result

    attachment = {
        "file_id": upload_result.get("file_id", ""),
        "name": display_name or upload_result.get("name", "download"),
        "size_bytes": upload_result.get("size_bytes", 0),
        "mime": upload_result.get("mime", "application/octet-stream"),
        "download_path": upload_result.get("download_path", ""),
    }
    if not attachment["download_path"]:
        return {"error": "Gateway 未返回 download_path", "raw": upload_result}

    from_agent = _local_agent_id()
    transfer = await request_fleet_transfer(
        from_agent_id=from_agent,
        to_agent_id=to_agent,
        to_user_id=to_user,
        thread_id=thread_id,
        user_id=user_id or to_user,
        uploads=[attachment],
    )
    if transfer.get("error"):
        return transfer

    dest = to_agent or to_user
    status = transfer.get("status", "pending")
    transfer_id = transfer.get("transfer_id", "")
    if to_user:
        return {
            "message": f"已推送「{attachment['name']}」到 {dest}",
            "status": status,
            "transfer_id": transfer_id,
            "attachments": [attachment],
            "max_bytes": DEFAULT_MAX_BYTES,
        }
    return {
        "message": (
            f"已发起跨箱传输「{attachment['name']}」→ {dest}"
            f"（{status}，transfer_id={transfer_id}）"
        ),
        "status": status,
        "transfer_id": transfer_id,
        "to_agent_id": to_agent,
        "max_bytes": DEFAULT_MAX_BYTES,
    }
