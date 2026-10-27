"""Shared runtime records. A pending run is the paused half of one decision."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class PendingRun:
    thread_id: str
    device_id: str  # Web connection id (conn-*)
    user_text: str
    system_prompt: str
    user_id: str = ""
    run_started_at: float = field(default_factory=time.monotonic)
    trace_id: str = ""


def pending_user_id(pending: PendingRun) -> str:
    if pending.user_id:
        return pending.user_id
    if ":" in pending.thread_id:
        return pending.thread_id.split(":", 1)[0]
    return pending.device_id


def format_tool_results(tool_results: list[dict]) -> str:
    if not tool_results:
        return ""
    parts = []
    for item in tool_results:
        name = item.get("tool_name", "unknown")
        result = item.get("result", "")
        parts.append(f"{name}: {result}")
    return "\n".join(parts)


def decision_succeeded(reply_text: str) -> bool:
    return not (reply_text or "").startswith("❌")
