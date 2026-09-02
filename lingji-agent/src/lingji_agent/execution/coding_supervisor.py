"""coding_run 监工 — Fleet 4.0e。不进 LangGraph。"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

JOBS_ROOT_SENTINEL = "$JOBS_ROOT"
INPUT_NEEDLES = ("Waiting for input", "Please choose")
_LOCK_NAME = ".coding_lock"


def normalize_git_url(url: str) -> str:
    text = (url or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    path = (parsed.path or "").rstrip("/").lower()
    if path.endswith(".git"):
        path = path[:-4]
    host = (parsed.netloc or "").lower()
    scheme = (parsed.scheme or "https").lower()
    if not host:
        return text.lower().rstrip("/").removesuffix(".git")
    return urlunparse((scheme, host, path, "", "", ""))


def git_url_allowed(url: str, allowlist: list[str] | None) -> bool:
    if not url or not allowlist:
        return False
    target = normalize_git_url(url)
    return any(normalize_git_url(item) == target for item in allowlist if item)


def detect_needs_input(log_text: str) -> bool:
    text = log_text or ""
    return any(needle in text for needle in INPUT_NEEDLES)


def job_work_dir(jobs_root: Path, job_id: str) -> Path:
    return Path(jobs_root) / job_id


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _lock_path(jobs_root: Path) -> Path:
    return Path(jobs_root) / _LOCK_NAME


def _read_lock_pid(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def try_acquire_lock(jobs_root: Path, pid: int) -> bool:
    root = Path(jobs_root)
    root.mkdir(parents=True, exist_ok=True)
    lock = _lock_path(root)
    existing = _read_lock_pid(lock) if lock.exists() else None
    if existing is not None and existing != pid and pid_alive(existing):
        return False
    lock.write_text(str(pid), encoding="utf-8")
    return True


def release_lock(jobs_root: Path, pid: int) -> None:
    lock = _lock_path(Path(jobs_root))
    if not lock.exists():
        return
    existing = _read_lock_pid(lock)
    if existing == pid:
        try:
            lock.unlink()
        except OSError:
            pass


def _default_clone(url: str, dest: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dest)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return str(exc)
    if proc.returncode == 0:
        return None
    err = (proc.stderr or proc.stdout or "git clone failed").strip()
    return err or "git clone failed"


def _read_job_pid(job_dir: Path) -> int | None:
    pid_file = job_dir / ".pid"
    if not pid_file.exists():
        return None
    return _read_lock_pid(pid_file)


def prepare_job_workspace(
    *,
    jobs_root: Path,
    job_id: str,
    step_id: str,
    brief: str,
    runner: str,
    timeout_sec: int | float,
    source_git: str = "",
    allowlist: list[str] | None = None,
    clone: Callable[[str, Path], str | None] | None = None,
) -> tuple[Path | None, str]:
    if not (brief or "").strip():
        return None, "brief_missing"

    source = (source_git or "").strip()
    if source and not git_url_allowed(source, allowlist):
        return None, "source_git not allowed"

    root = Path(jobs_root)
    root.mkdir(parents=True, exist_ok=True)
    job_dir = job_work_dir(root, job_id)

    if job_dir.exists():
        existing_pid = _read_job_pid(job_dir)
        if existing_pid is not None and pid_alive(existing_pid):
            return None, "executor_busy"
        stale = root / f"{job_id}.stale-{int(time.time())}"
        job_dir.rename(stale)

    job_dir.mkdir(parents=True, exist_ok=False)
    (job_dir / "logs").mkdir()
    (job_dir / "out").mkdir()
    workspace = job_dir / "workspace"
    workspace.mkdir()

    (job_dir / "brief.md").write_text(brief, encoding="utf-8")
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {
        "job_id": job_id,
        "step_id": step_id,
        "runner": runner,
        "timeout_sec": timeout_sec,
        "started_at": started_at,
    }
    (job_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False),
        encoding="utf-8",
    )

    if source:
        clone_fn = clone if clone is not None else _default_clone
        # git clone needs a non-existing or empty dest; remove empty placeholder
        try:
            workspace.rmdir()
        except OSError:
            pass
        err = clone_fn(source, workspace)
        if err:
            return None, err
        workspace.mkdir(parents=True, exist_ok=True)

    return job_dir, ""
