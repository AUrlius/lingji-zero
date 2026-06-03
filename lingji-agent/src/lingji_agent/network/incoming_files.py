"""G6.2 — 处理手机/Web 经 Gateway 上传的文件并落盘到 PC"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from lingji_agent.execution.sandbox import validate_path
from lingji_agent.foundation import run_metrics
from lingji_agent.network.file_download import download_file_from_gateway

logger = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-()\u4e00-\u9fff]+")
_ORGANIZE_HINT = re.compile(
    r"(放到|移至|移到|放进|移动到|转移到|复制到|拷贝到|整理到|归类到|归档到)"
)


def sanitize_filename(name: str) -> str:
    """只保留 basename，拒绝 . / .. 等路径逃逸。"""
    base = Path(name.strip()).name
    if not base or base in (".", ".."):
        base = "upload"
    cleaned = _SAFE_NAME.sub("_", base) or "upload"
    if cleaned in (".", ".."):
        cleaned = "upload"
    return cleaned[:200]


def _resolve_dest_under_base(base: Path, name: str) -> Path | None:
    """解析目标路径并确保落在 base 目录内。"""
    dest = (base / name).resolve()
    try:
        dest.relative_to(base.resolve())
    except ValueError:
        return None
    return dest


def text_implies_file_organization(text: str) -> bool:
    """用户文字是否要求将上传文件整理/移动到其他目录。"""
    return bool(_ORGANIZE_HINT.search(text.strip()))


def uploads_all_saved(results: list[dict], expected: int) -> bool:
    saved = [r for r in results if r.get("path")]
    return expected > 0 and len(saved) == expected


def format_saved_reply(results: list[dict]) -> str:
    ok = [r for r in results if r.get("path")]
    if not ok:
        return "❌ 未保存任何文件。"
    lines = [f"✅ 已保存 {len(ok)} 个文件到电脑："]
    for r in ok:
        lines.append(f"- {r.get('name', 'file')} → {r['path']}")
    return "\n".join(lines)


def format_upload_errors(results: list[dict]) -> str:
    errors = [r for r in results if r.get("error")]
    if not errors:
        return "❌ 文件保存失败。"
    lines = ["❌ 文件保存失败："]
    for e in errors:
        lines.append(f"- {e.get('name', '?')}: {e['error']}")
    return "\n".join(lines)


def validate_incoming_dir_config(incoming_dir: str) -> Path:
    """解析 incoming_dir；若等于 ~/Downloads 本身则视为配置错误。"""
    resolved = Path(incoming_dir).expanduser().resolve()
    downloads = (Path.home() / "Downloads").resolve()
    if resolved == downloads:
        raise ValueError(
            f"incoming_dir 不能为 Downloads 本身 ({resolved})，"
            "请设为 ~/Downloads/LingjiIncoming"
        )
    if not validate_path(str(resolved)):
        raise ValueError(f"incoming_dir 不在允许路径: {resolved}")
    return resolved


async def save_uploads_to_pc(
    uploads: list[dict],
    *,
    incoming_dir: str,
    gateway_host: str,
    gateway_port: int,
    auth_token: str,
) -> tuple[str, list[dict]]:
    """下载 uploads[] 到 incoming_dir，返回 (追加到 user 消息的文本, 结果列表)。"""
    base = Path(incoming_dir).expanduser().resolve()
    if not validate_path(str(base)):
        return "", [{"error": f"incoming_dir 不在允许路径: {base}"}]

    base.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    results: list[dict] = []

    for item in uploads:
        file_id = item.get("file_id") or item.get("fileId") or ""
        name = sanitize_filename(item.get("name") or file_id or "upload")
        download_path = item.get("download_path") or item.get("downloadPath") or ""
        if not file_id and not download_path:
            results.append({"error": "缺少 file_id"})
            continue

        dest = _resolve_dest_under_base(base, name)
        if dest is None:
            results.append({"name": name, "error": "非法文件名（路径逃逸）"})
            lines.append(f"- {name}: 失败 (非法文件名)")
            continue

        if dest.exists():
            stem = dest.stem
            suffix = dest.suffix
            for i in range(1, 1000):
                candidate = base / f"{stem}_{i}{suffix}"
                if not candidate.exists():
                    resolved = _resolve_dest_under_base(base, candidate.name)
                    if resolved is None:
                        break
                    dest = resolved
                    break

        outcome = await download_file_from_gateway(
            file_id=file_id,
            download_path=download_path,
            dest_path=dest,
            host=gateway_host,
            port=gateway_port,
            auth_token=auth_token,
        )
        if outcome.get("error"):
            results.append({"name": name, **outcome})
            lines.append(f"- {name}: 失败 ({outcome['error']})")
        else:
            path = outcome["path"]
            results.append({"name": name, "path": path, "size_bytes": outcome.get("size_bytes", 0)})
            lines.append(f"- {name} → {path}")
            logger.info("saved_upload name=%s dest=%s base=%s", name, path, base)
            run_metrics.increment("upload_saved_total")

    if not lines:
        return "", results
    block = "[用户上传文件]\n" + "\n".join(lines)
    return block, results
