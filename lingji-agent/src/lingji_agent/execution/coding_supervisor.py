"""coding_run 监工 — Fleet 4.0e。不进 LangGraph。"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from lingji_agent.execution.hermes_session import argv_list

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


def log_tail(path: Path, max_bytes: int = 4096) -> str:
    p = Path(path)
    if not p.is_file():
        return ""
    size = p.stat().st_size
    with p.open("rb") as fh:
        if size > max_bytes:
            fh.seek(size - max_bytes)
        data = fh.read(max_bytes)
    return data.decode("utf-8", errors="replace")


def build_evidence(
    *,
    runner,
    workspace,
    exit_code,
    reason,
    log_path,
    summary_path,
    questions_path,
) -> dict:
    ev = {
        "runner": runner,
        "workspace": str(workspace),
        "exit_code": exit_code,
        "reason": reason,
        "log_tail": log_tail(Path(log_path)) if log_path else "",
        "summary": "",
    }
    summary = Path(summary_path) if summary_path else None
    if summary is not None and summary.is_file():
        ev["summary"] = summary.read_text(encoding="utf-8", errors="replace")
    if reason == "needs_input":
        questions = Path(questions_path) if questions_path else None
        ev["questions"] = (
            questions.read_text(encoding="utf-8", errors="replace")
            if questions is not None and questions.is_file()
            else ""
        )
    return ev


def kill_process_tree(pid: int) -> None:
    if pid <= 0:
        return
    pgid = None
    try:
        pgid = os.getpgid(pid)
    except (AttributeError, OSError):
        pgid = None
    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGKILL)
            return
        except OSError:
            pass
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def _write_heartbeat(job_dir: Path) -> None:
    path = Path(job_dir) / "logs" / "heartbeat"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        encoding="utf-8",
    )


def _read_log_slice(path: Path, start: int, size: int) -> str:
    if size <= start:
        return ""
    with path.open("rb") as fh:
        fh.seek(start)
        data = fh.read(size - start)
    return data.decode("utf-8", errors="replace")


async def _reap(proc) -> int | None:
    if proc.poll() is not None:
        return proc.returncode

    def wait() -> int | None:
        try:
            return proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            return proc.poll()

    return await asyncio.to_thread(wait)


def _cli_result(*, ok: bool, reason: str, exit_code, job_dir: Path) -> dict:
    evidence = build_evidence(
        runner="cursor",
        workspace=Path(job_dir) / "workspace",
        exit_code=exit_code,
        reason=reason,
        log_path=Path(job_dir) / "logs" / "run.log",
        summary_path=Path(job_dir) / "out" / "summary.md",
        questions_path=Path(job_dir) / "out" / "questions.md",
    )
    return {"ok": ok, "reason": reason, "exit_code": exit_code, "evidence": evidence}


async def supervise_process(
    *,
    proc,
    job_dir: Path,
    timeout_sec: float,
    hung_sec: float,
    heartbeat_sec: float,
    progress_sec: float,
    on_progress=None,
    clock=None,
) -> dict:
    tick = clock or time.monotonic
    job_dir = Path(job_dir)
    log_path = job_dir / "logs" / "run.log"
    started = tick()
    last_hb = started - float(heartbeat_sec or 0) - 1
    last_progress = started
    last_growth = started
    last_size = log_path.stat().st_size if log_path.is_file() else 0
    poll = 0.05

    while True:
        now = tick()
        if now - last_hb >= float(heartbeat_sec):
            _write_heartbeat(job_dir)
            last_hb = now

        size = log_path.stat().st_size if log_path.is_file() else 0
        if size > last_size:
            chunk = _read_log_slice(log_path, last_size, size)
            last_size = size
            last_growth = now
            if detect_needs_input(chunk):
                (job_dir / "out").mkdir(parents=True, exist_ok=True)
                (job_dir / "out" / "questions.md").write_text(
                    log_tail(log_path, 2048),
                    encoding="utf-8",
                )
                kill_process_tree(getattr(proc, "pid", 0) or 0)
                code = await _reap(proc)
                return {"ok": False, "reason": "needs_input", "exit_code": code}

        code = proc.poll()
        if code is not None:
            reason = "ok" if code == 0 else "crash"
            return {"ok": code == 0, "reason": reason, "exit_code": code}

        if now - started >= float(timeout_sec):
            kill_process_tree(getattr(proc, "pid", 0) or 0)
            code = await _reap(proc)
            return {"ok": False, "reason": "timeout", "exit_code": code}

        if now - last_growth >= float(hung_sec):
            kill_process_tree(getattr(proc, "pid", 0) or 0)
            code = await _reap(proc)
            return {"ok": False, "reason": "hung", "exit_code": code}

        if on_progress is not None and now - last_progress >= float(progress_sec):
            on_progress(
                build_evidence(
                    runner="cursor",
                    workspace=job_dir / "workspace",
                    exit_code=None,
                    reason="",
                    log_path=log_path,
                    summary_path=job_dir / "out" / "summary.md",
                    questions_path=job_dir / "out" / "questions.md",
                )
            )
            last_progress = now

        await asyncio.sleep(poll)


async def run_coding_cli(
    *,
    start_cmd: list[str],
    job_dir: Path,
    timeout_sec,
    hung_sec,
    heartbeat_sec,
    progress_sec,
    argv_check=argv_list,
    spawn=None,
    on_progress=None,
) -> dict:
    job_dir = Path(job_dir)
    check = argv_check if argv_check is not None else argv_list
    try:
        argv = check(start_cmd)
    except (TypeError, ValueError):
        return _cli_result(ok=False, reason="runner_missing", exit_code=None, job_dir=job_dir)
    if not argv:
        return _cli_result(ok=False, reason="runner_missing", exit_code=None, job_dir=job_dir)

    workspace = job_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    log_path = job_dir / "logs" / "run.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    popen = spawn if spawn is not None else subprocess.Popen
    log_f = log_path.open("ab")
    try:
        try:
            proc = popen(
                argv,
                cwd=str(workspace),
                stdin=subprocess.DEVNULL,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError:
            return _cli_result(ok=False, reason="runner_missing", exit_code=None, job_dir=job_dir)

        (job_dir / ".pid").write_text(str(proc.pid), encoding="utf-8")
        outcome = await supervise_process(
            proc=proc,
            job_dir=job_dir,
            timeout_sec=timeout_sec,
            hung_sec=hung_sec,
            heartbeat_sec=heartbeat_sec,
            progress_sec=progress_sec,
            on_progress=on_progress,
        )
    finally:
        log_f.close()

    return _cli_result(
        ok=bool(outcome["ok"]),
        reason=str(outcome["reason"]),
        exit_code=outcome.get("exit_code"),
        job_dir=job_dir,
    )
