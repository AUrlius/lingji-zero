"""Mission 预授权 approval_scope — Fleet 4.0d WP1

调度 Agent 创建 Job 时写入 scope；执行层用 validate_playbook / validate_path
判断 playbook 与路径是否在授权范围内。JOB_DELEGATE handler 会调用 validate_playbook。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from lingji_agent.execution.coding_supervisor import JOBS_ROOT_SENTINEL, normalize_git_url

_DEFAULT_ALLOWED_PATHS = ["/mnt/e/LingjiPlan/LingjiZero"]
_SENSITIVE_EXACT = ("~/.ssh", "/root/.ssh")
PLAYBOOK_CODING_CURSOR = "coding.cursor"
_CODING_RUNNER_CURSOR = "cursor"


def _as_utc(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _rfc3339_utc(dt: datetime) -> str:
    dt = _as_utc(dt).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_expires_at(raw: str) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


ESCALATION_SCHEDULER = "scheduler"
ESCALATION_USER = "user"
_JOB_ACTIVE_STATUS = frozenset({"running", "dispatched", "waiting"})


def default_scope(playbook_id: str, *, now: datetime | None = None) -> dict:
    """Default 1h Mission 预授权：单 playbook、LingjiZero 路径前缀、Tier 0 免批。"""
    now_utc = _as_utc(now)
    return {
        "expires_at": _rfc3339_utc(now_utc + timedelta(hours=1)),
        "playbooks": [playbook_id],
        "allowed_paths": list(_DEFAULT_ALLOWED_PATHS),
        "auto_approve_tier0": True,
        "auto_approve_hitl_in_scope": True,
    }


def validate_playbook(
    scope: dict | None, playbook_id: str, *, now: datetime | None = None
) -> tuple[bool, str]:
    if not scope:
        return False, "approval_scope missing"
    now_utc = _as_utc(now)
    expires = _parse_expires_at(str(scope.get("expires_at") or ""))
    if expires is None or expires < now_utc:
        return False, "approval_scope expired"
    playbooks = scope.get("playbooks") or []
    if playbook_id not in playbooks:
        return False, "playbook not in approval_scope"
    return True, ""


def default_coding_scope(
    *,
    jobs_root_sentinel: str = JOBS_ROOT_SENTINEL,
    timeout_sec: int = 14400,
    source_git: str = "",
    runner: str = "cursor",
    now: datetime | None = None,
) -> dict:
    """Default coding_run 预授权：coding.cursor + jobs_root 哨兵路径。"""
    now_utc = _as_utc(now)
    expires = now_utc + timedelta(seconds=timeout_sec) + timedelta(minutes=15)
    return {
        "expires_at": _rfc3339_utc(expires),
        "playbooks": [PLAYBOOK_CODING_CURSOR],
        "runners": [runner],
        "allowed_paths": [jobs_root_sentinel],
        "max_timeout_sec": timeout_sec,
        "source_git": source_git or "",
        "auto_approve_tier0": False,
    }


def validate_coding_scope(
    scope: dict | None,
    *,
    playbook_id: str,
    runner: str,
    jobs_root: str,
    source_git: str = "",
    now: datetime | None = None,
) -> tuple[bool, str]:
    if not scope:
        return False, "approval_scope missing"
    now_utc = _as_utc(now)
    expires = _parse_expires_at(str(scope.get("expires_at") or ""))
    if expires is None or expires < now_utc:
        return False, "approval_scope expired"
    playbooks = scope.get("playbooks") or []
    if playbook_id != PLAYBOOK_CODING_CURSOR or playbook_id not in playbooks:
        return False, "playbook not in approval_scope"
    runners = scope.get("runners")
    if not isinstance(runners, list):
        runners = []
    if runner != _CODING_RUNNER_CURSOR or runner not in runners:
        return False, "runner not in approval_scope"
    if not (jobs_root or "").strip():
        return False, "jobs_root empty"
    root = jobs_root.strip()
    allowed_raw: list[Any] = scope.get("allowed_paths") or []
    allowed: list[str] = []
    for prefix in allowed_raw:
        if not isinstance(prefix, str):
            continue
        allowed.append(prefix.replace(JOBS_ROOT_SENTINEL, root))
    if not any(_path_under_prefix(root, p) for p in allowed):
        return False, "path not in approval_scope"
    plan_git = (source_git or "").strip()
    scope_git = str(scope.get("source_git") or "").strip()
    if scope_git and not plan_git:
        return False, "source_git not in approval_scope"
    if plan_git and scope_git and normalize_git_url(plan_git) != normalize_git_url(scope_git):
        return False, "source_git not in approval_scope"
    return True, ""


def _is_sensitive_path(path: str) -> bool:
    if path in _SENSITIVE_EXACT or path.startswith("~/.ssh/") or path.startswith("/root/.ssh/"):
        return True
    if "/.ssh/" in path:
        return True
    return False


def _path_under_prefix(path: str, prefix: str) -> bool:
    if path == prefix:
        return True
    root = prefix.rstrip("/") + "/"
    return path.startswith(root)


def validate_path(scope: dict | None, path: str) -> tuple[bool, str]:
    if not path:
        return True, ""
    if _is_sensitive_path(path):
        return False, "sensitive path"
    allowed: list[Any] = (scope or {}).get("allowed_paths") or []
    for prefix in allowed:
        if isinstance(prefix, str) and _path_under_prefix(path, prefix):
            return True, ""
    return False, "path not in approval_scope"


def job_binds_executor(job: dict | None, executor_id: str) -> bool:
    if not job or not executor_id:
        return False
    plan = job.get("plan") if isinstance(job.get("plan"), dict) else {}
    if (plan or {}).get("executor_id") == executor_id:
        return True
    for st in job.get("steps") or []:
        if isinstance(st, dict) and (st.get("executor_id") or "") == executor_id:
            return True
    return False


def pick_active_job_for_executor(jobs: list | None, executor_id: str) -> dict | None:
    """Newest active Job whose plan/steps bind this executor."""
    candidates: list[dict] = []
    for job in jobs or []:
        if not isinstance(job, dict):
            continue
        if (job.get("status") or "") not in _JOB_ACTIVE_STATUS:
            continue
        if job_binds_executor(job, executor_id):
            candidates.append(job)
    if not candidates:
        return None
    candidates.sort(key=lambda j: str(j.get("updated_at") or ""), reverse=True)
    return candidates[0]


def _command_allowed(scope: dict, command: str) -> bool:
    allowed: list[Any] = scope.get("allowed_commands") or []
    if not allowed:
        return True
    cmd = (command or "").strip()
    for prefix in allowed:
        if not isinstance(prefix, str):
            continue
        p = prefix.strip()
        if p and (cmd == p or cmd.startswith(p)):
            return True
    return False


def classify_hitl(
    scope: dict | None,
    tool: str,
    args: dict | None = None,
    *,
    now: datetime | None = None,
) -> str:
    """Return scheduler | user for a Job-bound CRITICAL interrupt.

    Caller must only invoke this when an active Job is already bound.
    Missing/expired scope, explicit opt-out, sensitive paths → user.
    """
    if not scope:
        return ESCALATION_USER
    now_utc = _as_utc(now)
    expires = _parse_expires_at(str(scope.get("expires_at") or ""))
    if expires is None or expires < now_utc:
        return ESCALATION_USER
    if scope.get("auto_approve_hitl_in_scope") is False:
        return ESCALATION_USER

    fn = (tool or "").strip()
    raw_args = args if isinstance(args, dict) else {}

    if fn == "delete_file":
        path = str(raw_args.get("path") or "")
        if not path:
            return ESCALATION_USER
        ok, _reason = validate_path(scope, path)
        return ESCALATION_SCHEDULER if ok else ESCALATION_USER

    if fn == "execute_command":
        cwd = str(raw_args.get("cwd") or "")
        if cwd:
            ok, _reason = validate_path(scope, cwd)
            if not ok:
                return ESCALATION_USER
        if not _command_allowed(scope, str(raw_args.get("command") or "")):
            return ESCALATION_USER
        return ESCALATION_SCHEDULER

    return ESCALATION_USER
