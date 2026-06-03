"""Gateway 临时文件上传客户端（G6）"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path

import httpx

DEFAULT_MAX_BYTES = 50 * 1024 * 1024


def _gateway_base_url(host: str | None = None, port: int | None = None) -> str:
    host = host or os.getenv("LINGJI_GATEWAY_HOST", "127.0.0.1")
    port = port or int(os.getenv("LINGJI_GATEWAY_PORT", "8765"))
    scheme = "https" if port == 443 else "http"
    default_port = 443 if scheme == "https" else 8765
    if (scheme == "https" and port == 443) or (scheme == "http" and port == default_port):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


async def upload_file_to_gateway(
    file_path: Path,
    *,
    host: str | None = None,
    port: int | None = None,
    auth_token: str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict:
    """POST /files 上传单个文件，返回 Gateway JSON（含 download_path）。"""
    path = file_path.expanduser().resolve()
    if not path.is_file():
        return {"error": f"不是文件: {path}"}
    size = path.stat().st_size
    if size > max_bytes:
        return {
            "error": f"文件过大 ({size} bytes)，上限 {max_bytes} bytes，请缩小或打包 zip",
        }

    token = auth_token if auth_token is not None else os.getenv("LINGJI_AUTH_TOKEN", "")
    base = _gateway_base_url(host, port)
    url = f"{base}/files"
    mime, _ = mimetypes.guess_type(path.name)
    if not mime:
        mime = "application/octet-stream"

    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=120.0) as session:
            with path.open("rb") as fh:
                resp = await session.post(
                    url,
                    files={"file": (path.name, fh, mime)},
                    headers=headers,
                )
            if resp.status_code >= 400:
                return {"error": f"Gateway 上传失败 ({resp.status_code}): {resp.text[:200]}"}
            return resp.json()
    except Exception as e:
        return {"error": f"上传 Gateway 失败: {e}"}
