"""coding_run 监工 — Fleet 4.0e。不进 LangGraph。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import subprocess
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from lingji_agent.execution.hermes_session import argv_list

logger = logging.getLogger(__name__)

JOBS_ROOT_SENTINEL = "$JOBS_ROOT"
INPUT_NEEDLES = ("Waiting for input", "Please choose")
_LOCK_NAME = ".coding_lock"
_JOB_DIR_RE = re.compile(r"^LJ-[0-9A-F]{8,}$")
_DEFAULT_HUNG_SEC = 900


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


_LOCK_EXCL_FLAGS = os.O_CREAT | os.O_EXCL | os.O_WRONLY
_claim_lock = asyncio.Lock()
_coding_busy = False


def _create_lock_file(lock: Path) -> int | None:
    try:
        return os.open(lock, _LOCK_EXCL_FLAGS)
    except FileExistsError:
        return None


def try_acquire_lock(jobs_root: Path, pid: int) -> bool:
    """Acquire jobs_root/.coding_lock. Any live holder (including this pid) is busy."""
    root = Path(jobs_root)
    root.mkdir(parents=True, exist_ok=True)
    lock = _lock_path(root)
    fd = _create_lock_file(lock)
    if fd is None:
        existing = _read_lock_pid(lock)
        if existing is not None and pid_alive(existing):
            return False
        try:
            lock.unlink()
        except OSError:
            return False
        fd = _create_lock_file(lock)
        if fd is None:
            return False
    try:
        os.write(fd, str(pid).encode("utf-8"))
    finally:
        os.close(fd)
    return True


async def _claim_executor(jobs_root: Path, pid: int) -> bool:
    """Check-and-set only. Caller must run the CLI outside this gate."""
    global _coding_busy
    async with _claim_lock:
        if _coding_busy:
            return False
        if not try_acquire_lock(jobs_root, pid):
            return False
        _coding_busy = True
        return True


def _release_executor(jobs_root: Path, pid: int) -> None:
    global _coding_busy
    try:
        release_lock(jobs_root, pid)
    finally:
        _coding_busy = False


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


def _heartbeat_fresh(job_dir: Path, hung_sec: float) -> bool:
    hb = job_dir / "logs" / "heartbeat"
    if not hb.is_file():
        return False
    return (time.time() - hb.stat().st_mtime) <= float(hung_sec)


def _job_still_running(job_dir: Path, hung_sec: float) -> bool:
    pid = _read_job_pid(job_dir)
    if pid is None or not pid_alive(pid):
        return False
    return _heartbeat_fresh(job_dir, hung_sec)


def _read_job_meta(job_dir: Path) -> dict | None:
    meta_path = job_dir / "meta.json"
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict):
        return None
    job_id = meta.get("job_id")
    step_id = meta.get("step_id")
    if not job_id or not step_id:
        return None
    return meta


def list_orphan_reports(jobs_root: Path, *, hung_sec: float = _DEFAULT_HUNG_SEC) -> list[dict]:
    root = Path(jobs_root)
    if not root.is_dir():
        return []

    reports: list[dict] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not _JOB_DIR_RE.match(entry.name):
            continue
        meta = _read_job_meta(entry)
        if meta is None:
            continue
        if _job_still_running(entry, hung_sec):
            continue
        evidence = build_evidence(
            runner=meta.get("runner", "cursor"),
            workspace=entry / "workspace",
            exit_code=None,
            reason="executor_lost",
            log_path=entry / "logs" / "run.log",
            summary_path=entry / "out" / "summary.md",
            questions_path=entry / "out" / "questions.md",
        )
        reports.append(
            {
                "job_id": meta["job_id"],
                "step_id": meta["step_id"],
                "reason": "executor_lost",
                "evidence": evidence,
            }
        )
    return reports


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


def _empty_evidence(*, runner: str, reason: str) -> dict:
    return build_evidence(
        runner=runner,
        workspace="",
        exit_code=None,
        reason=reason,
        log_path="",
        summary_path="",
        questions_path="",
    )


async def handle_job_delegate(payload: dict, coding_cfg, *, report, get_job=None) -> None:
    """JOB_DELEGATE 编码分支：coding.* 才处理，禁止走 run_playbook。"""
    p = payload or {}
    playbook_id = p.get("playbook_id") or ""
    if not str(playbook_id).startswith("coding."):
        return

    job_id = p.get("job_id") or ""
    step_id = p.get("step_id") or ""
    runner = (p.get("runner") or "cursor").strip() or "cursor"
    source_git = (p.get("source_git") or "").strip()
    scope = p.get("approval_scope")
    jobs_root = (getattr(coding_cfg, "jobs_root", None) or "").strip()
    start_cmd = [str(x) for x in (getattr(coding_cfg, "start_cmd", None) or [])]

    async def _fail(reason: str, *, error: str = "", evidence: dict | None = None) -> None:
        await report(
            job_id,
            step_id,
            status="failed",
            evidence=evidence if evidence is not None else _empty_evidence(runner=runner, reason=reason),
            error=error or reason,
        )

    if not jobs_root or not start_cmd:
        await _fail(
            "runner_missing",
            error="coding runner missing: jobs_root 或 start_cmd 未配置",
        )
        return

    brief = (p.get("brief") or "").strip()
    if not brief and get_job is not None:
        job = await get_job(job_id)
        if isinstance(job, dict):
            plan = job.get("plan") if isinstance(job.get("plan"), dict) else {}
            brief = str(plan.get("brief") or job.get("brief") or "").strip()
    if not brief:
        await _fail("brief_missing")
        return

    raw_timeout = p.get("timeout_sec")
    try:
        if raw_timeout in (None, ""):
            timeout_sec = int(coding_cfg.timeout_sec)
        else:
            timeout_sec = int(raw_timeout)
    except (TypeError, ValueError):
        timeout_sec = int(coding_cfg.timeout_sec)
    if timeout_sec <= 0:
        timeout_sec = int(coding_cfg.timeout_sec)
    hard = int(getattr(coding_cfg, "timeout_hard_sec", 3600) or 3600)
    timeout_sec = min(timeout_sec, hard)

    from lingji_agent.execution.approval_scope import validate_coding_scope

    ok, why = validate_coding_scope(
        scope if isinstance(scope, dict) else None,
        playbook_id=playbook_id,
        runner=runner,
        jobs_root=jobs_root,
        source_git=source_git,
    )
    if not ok:
        await _fail("scope", error=why)
        return

    allowlist = list(getattr(coding_cfg, "source_git_allowlist", None) or [])
    if source_git and not git_url_allowed(source_git, allowlist):
        await _fail("scope", error="source_git not allowed")
        return

    root = Path(jobs_root)
    lock_pid = os.getpid()
    if not await _claim_executor(root, lock_pid):
        await _fail("executor_busy")
        return

    try:
        job_dir, prep_reason = prepare_job_workspace(
            jobs_root=root,
            job_id=job_id,
            step_id=step_id,
            brief=brief,
            runner=runner,
            timeout_sec=timeout_sec,
            source_git=source_git,
            allowlist=allowlist,
        )
        if job_dir is None:
            reason = prep_reason or "scope"
            ev_reason = "scope" if reason == "source_git not allowed" else reason
            await _fail(ev_reason, error=reason)
            return

        progress_tasks: set[asyncio.Task] = set()

        def _on_progress_done(task: asyncio.Task) -> None:
            progress_tasks.discard(task)
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                logger.warning("coding progress report failed: %s", exc)

        def _on_progress(evidence: dict) -> None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            task = loop.create_task(
                report(job_id, step_id, status="progress", evidence=evidence)
            )
            progress_tasks.add(task)
            task.add_done_callback(_on_progress_done)

        result = await run_coding_cli(
            start_cmd=start_cmd,
            job_dir=job_dir,
            timeout_sec=timeout_sec,
            hung_sec=getattr(coding_cfg, "hung_sec", _DEFAULT_HUNG_SEC),
            heartbeat_sec=getattr(coding_cfg, "heartbeat_sec", 15),
            progress_sec=getattr(coding_cfg, "progress_sec", 30),
            on_progress=_on_progress,
        )
        pending = list(progress_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        reason = str(result.get("reason") or "")
        evidence = result.get("evidence") or {}
        if reason == "ok":
            await report(
                job_id,
                step_id,
                status="completed",
                evidence=evidence,
                error="",
            )
        else:
            await report(
                job_id,
                step_id,
                status="failed",
                evidence=evidence,
                error=reason or "crash",
            )
    finally:
        _release_executor(root, lock_pid)


async def recover_orphan_coding_jobs(
    jobs_root: Path,
    *,
    report,
    hung_sec: float = _DEFAULT_HUNG_SEC,
    kill=None,
) -> list[dict]:
    """Startup recover: report executor_lost. Kill tree only if heartbeat is stale.

    Residual (first cut): live pid + fresh heartbeat is skipped even when this
    process is not the parent — no reattach supervise, to avoid double-supervising.
    """
    kill_fn = kill if kill is not None else kill_process_tree
    if not jobs_root:
        return []
    root = Path(jobs_root)
    if not root.is_dir():
        return []

    items = list_orphan_reports(root, hung_sec=hung_sec)
    for item in items:
        job_dir = root / str(item["job_id"])
        if not _heartbeat_fresh(job_dir, hung_sec):
            pid = _read_job_pid(job_dir)
            if pid is not None and pid_alive(pid):
                kill_fn(pid)
        await report(
            item["job_id"],
            item["step_id"],
            status="failed",
            error="executor_lost",
            evidence=item.get("evidence") or {},
        )
    return items

