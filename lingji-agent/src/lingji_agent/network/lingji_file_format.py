"""Format replies with user-visible Lingji file IDs (LF-ID)."""

from __future__ import annotations

from typing import Any


def append_lf_id_block(text: str, lingji_files: list[dict[str, Any]] | None) -> str:
    if not lingji_files:
        return text
    lines = [text.rstrip()] if text.strip() else []
    for item in lingji_files:
        lf_id = item.get("lingji_file_id") or ""
        name = item.get("name") or "file"
        if lf_id:
            lines.append(f"📎 灵机文件 ID：{lf_id}（{name}）")
    return "\n".join(lines)


def lingji_files_payload(lingji_files: list[dict[str, Any]] | None) -> dict[str, Any]:
    if not lingji_files:
        return {}
    return {"lingji_files": lingji_files}
