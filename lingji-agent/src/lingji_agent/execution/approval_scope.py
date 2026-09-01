"""Mission 预授权 approval_scope — Fleet 4.0d WP1

调度 Agent 创建 Job 时写入 scope；执行层用 validate_playbook / validate_path
判断 playbook 与路径是否在授权范围内。JOB_DELEGATE handler 会调用 validate_playbook。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

_DEFAULT_ALLOWED_PATHS = ["/mnt/e/LingjiPlan/LingjiZero"]
_SENSITIVE_EXACT = ("~/.ssh", "/root/.ssh")


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


def default_scope(playbook_id: str, *, now: datetime | None = None) -> dict:
    """Default 1h Mission 预授权：单 playbook、LingjiZero 路径前缀、Tier 0 免批。"""
    now_utc = _as_utc(now)
    return {
        "expires_at": _rfc3339_utc(now_utc + timedelta(hours=1)),
        "playbooks": [playbook_id],
        "allowed_paths": list(_DEFAULT_ALLOWED_PATHS),
        "auto_approve_tier0": True,
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
