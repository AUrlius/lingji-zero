"""重启自杀 playbook 的 Job 回执落盘 — Fleet 4.0d 重启后补报。

agent.restart 会 --stop 当前进程，来不及 POST report。
重启前写入 sidecar；新进程连上 Gateway 后再 report 并删除文件。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

SELF_KILLING_PLAYBOOKS = frozenset({"agent.restart"})
SIDECAR_NAME = "pending_job_report.json"

Reporter = Callable[..., Awaitable[dict]]


def should_defer_report(playbook_id: str) -> bool:
    return (playbook_id or "") in SELF_KILLING_PLAYBOOKS


def default_data_dir() -> Path:
    override = os.getenv("LINGJI_DATA_DIR")
    if override:
        return Path(override)
    # .../src/lingji_agent/execution/this.py → lingji-agent/data
    return Path(__file__).resolve().parents[3] / "data"


def sidecar_path(data_dir: Path) -> Path:
    return Path(data_dir) / SIDECAR_NAME


def write_pending(
    data_dir: Path,
    *,
    job_id: str,
    step_id: str,
    playbook_id: str,
    status: str = "completed",
    evidence: dict | None = None,
    error: str = "",
) -> Path:
    if not job_id or not step_id:
        raise ValueError("job_id and step_id required")
    dest = sidecar_path(data_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "job_id": job_id,
        "step_id": step_id,
        "playbook_id": playbook_id,
        "status": status or "completed",
        "evidence": evidence or {},
        "error": error or "",
        "written_at": datetime.now(timezone.utc).replace(microsecond=0).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(dest)
    logger.info("pending job report written job=%s path=%s", job_id, dest)
    return dest


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def clear_pending(data_dir: Path) -> None:
    _unlink(sidecar_path(data_dir))


def load_pending(data_dir: Path) -> dict[str, Any] | None:
    path = sidecar_path(data_dir)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("pending job report corrupt, discarding %s", path)
        _unlink(path)
        return None
    if not isinstance(raw, dict):
        _unlink(path)
        return None
    job_id = str(raw.get("job_id") or "").strip()
    step_id = str(raw.get("step_id") or "").strip()
    if not job_id or not step_id:
        logger.warning("pending job report missing ids, discarding %s", path)
        _unlink(path)
        return None
    raw["job_id"] = job_id
    raw["step_id"] = step_id
    return raw


async def flush_pending_report(
    data_dir: Path,
    *,
    reporter: Reporter | None = None,
) -> dict:
    """POST sidecar report. Success deletes file; Gateway error keeps it for retry."""
    pending = load_pending(data_dir)
    if pending is None:
        return {"skipped": True, "reason": "no sidecar"}

    evidence = dict(pending.get("evidence") or {})
    evidence["post_restart"] = True
    evidence.setdefault("playbook_id", pending.get("playbook_id") or "")

    if reporter is None:
        from lingji_agent.network.job_client import report_job_step

        async def reporter(job_id, step_id, *, status, evidence=None, error=""):
            return await report_job_step(
                job_id,
                step_id,
                status=status,
                evidence=evidence,
                error=error,
            )

    result = await reporter(
        pending["job_id"],
        pending["step_id"],
        status=pending.get("status") or "completed",
        evidence=evidence,
        error=pending.get("error") or "",
    )
    if result.get("error"):
        logger.warning(
            "pending job report flush failed job=%s: %s",
            pending["job_id"],
            result.get("error"),
        )
        return {"ok": False, "kept": True, "job_id": pending["job_id"], **result}

    clear_pending(data_dir)
    logger.info("pending job report flushed job=%s", pending["job_id"])
    return {"ok": True, "job_id": pending["job_id"], "result": result}
