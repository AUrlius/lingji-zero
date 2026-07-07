"""G6 远程文件推送工具：找文件 → 上传 Gateway → 返回 attachments"""

from __future__ import annotations

import fnmatch
import os
import tempfile
import zipfile
from pathlib import Path

from lingji_agent.execution.registry import RiskLevel, registry
from lingji_agent.execution.sandbox import PATH_ALLOWLIST, validate_path
from lingji_agent.network.file_upload import DEFAULT_MAX_BYTES, upload_file_to_gateway

SENSITIVE_KEYWORDS = ("合同", "密钥", "password", "secret", ".ssh", "id_rsa", "私钥")


def _is_sensitive_path(path: Path) -> bool:
    text = str(path).lower()
    name = path.name.lower()
    for kw in SENSITIVE_KEYWORDS:
        if kw.lower() in text or kw.lower() in name:
            return True
    return False


def _resolve_candidates(query: str, paths: list[str] | None) -> tuple[list[Path], str | None]:
    """解析候选文件路径；出错时返回 ( [], error )。"""
    if paths:
        resolved: list[Path] = []
        for p in paths:
            path = Path(p).expanduser().resolve()
            if not validate_path(str(path)):
                return [], f"路径不在允许范围: {p}"
            if not path.exists():
                return [], f"路径不存在: {p}"
            if path.is_dir():
                return [], f"是目录而非文件: {p}"
            resolved.append(path)
        return resolved, None

    if not query.strip():
        return [], "请提供 query 或 paths"

    keyword = query.strip()
    matches: list[Path] = []
    for root in PATH_ALLOWLIST:
        base = Path(os.path.expanduser(root))
        if not base.exists():
            continue
        for dirpath, _, filenames in os.walk(base):
            try:
                depth = len(Path(dirpath).relative_to(base).parts)
            except ValueError:
                continue
            if depth > 4:
                continue
            for fname in filenames:
                if keyword in fname or fnmatch.fnmatch(fname.lower(), f"*{keyword.lower()}*"):
                    candidate = Path(dirpath) / fname
                    if validate_path(str(candidate)) and candidate.is_file():
                        matches.append(candidate.resolve())
            if len(matches) >= 50:
                break
        if len(matches) >= 50:
            break

    if not matches:
        return [], f"未找到匹配「{keyword}」的文件"
    if len(matches) > 1:
        preview = [str(m) for m in matches[:10]]
        return [], (
            f"找到 {len(matches)} 个候选文件，请指定更精确的名称或 paths 参数。"
            f" 示例: {preview}"
        )
    return matches, None


def _prepare_upload_path(paths: list[Path]) -> tuple[Path | None, str | None, Path | None]:
    """单文件直接上传；同目录多文件 zip。返回 (upload_path, display_name, temp_to_cleanup)。"""
    if len(paths) == 1:
        return paths[0], paths[0].name, None

    parent = paths[0].parent
    if any(p.parent != parent for p in paths):
        return None, None, None

    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    zip_path = Path(tmp.name)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            zf.write(p, arcname=p.name)
    return zip_path, f"{parent.name}.zip", zip_path


@registry.register(
    name="send_file_to_user",
    description=(
        "将 PC 上的文件推送到手机/Web 聊天供下载。"
        "用户说「发给我/传到手机/下载」时必须使用此工具，禁止把文件内容读进聊天文本。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "用户描述或文件名关键词，如「商务洽谈 PPT」「合同 pdf」",
            },
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可选：已 search 到的精确文件路径（单文件或同目录多文件）",
            },
        },
    },
    risk=RiskLevel.WARN,
)
async def send_file_to_user(query: str = "", paths: list[str] | None = None) -> dict:
    """查找文件并上传到 Gateway，返回 attachments 供 AGENT_RES 合并。"""
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
        names = [str(p) for p in candidates]
        return {
            "error": "多个文件不在同一目录，请分别发送或指定单个 paths",
            "candidates": names,
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

    return {
        "message": f"已推送「{attachment['name']}」（{attachment['size_bytes']} bytes，1 小时内有效）",
        "attachments": [attachment],
        "max_bytes": DEFAULT_MAX_BYTES,
    }
