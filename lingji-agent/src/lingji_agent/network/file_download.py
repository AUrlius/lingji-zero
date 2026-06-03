"""Gateway 临时文件下载（G6.2 手机→PC 落盘）"""

from __future__ import annotations

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


async def download_file_from_gateway(
    *,
    file_id: str,
    download_path: str = "",
    dest_path: Path,
    host: str | None = None,
    port: int | None = None,
    auth_token: str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict:
    """从 Gateway GET /files/{id} 下载到 dest_path。"""
    token = auth_token if auth_token is not None else os.getenv("LINGJI_AUTH_TOKEN", "")
    base = _gateway_base_url(host, port)
    if download_path.startswith("http"):
        url = download_path
    elif download_path.startswith("/"):
        url = f"{base}{download_path}"
    else:
        query = f"?token={token}" if token else ""
        url = f"{base}/files/{file_id}{query}"

    headers: dict[str, str] = {}
    if token and "token=" not in url:
        headers["Authorization"] = f"Bearer {token}"

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        async with httpx.AsyncClient(timeout=120.0) as session:
            async with session.stream("GET", url, headers=headers, follow_redirects=True) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    return {
                        "error": f"Gateway 下载失败 ({resp.status_code}): {body[:200]!r}",
                    }
                total = 0
                with dest_path.open("wb") as out:
                    async for chunk in resp.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            return {"error": f"文件超过上限 {max_bytes} bytes"}
                        out.write(chunk)
        return {"path": str(dest_path), "size_bytes": total}
    except Exception as e:
        if dest_path.exists():
            dest_path.unlink(missing_ok=True)
        return {"error": f"下载失败: {e}"}
