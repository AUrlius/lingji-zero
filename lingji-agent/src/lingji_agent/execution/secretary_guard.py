"""调度 Agent 秘书护栏 — Fleet 4.0d WP4

远程运维意图下，调度端不应本机 execute_command。由 orchestrator 在 HITL 前调用。
"""

from __future__ import annotations

_REMOTE_OPS_HINTS = (
    "fleet send",
    "fleet_send",
    "发给青铜剑",
    "发到青铜剑",
    "青铜剑",
    "上海运维",
    "检查上海",
    "检查 agent",
    "重启 agent",
    "重启agent",
    "restart agent",
    "检查值守",
    "agent.status",
    "agent.restart",
)


def remote_ops_intent(text: str) -> bool:
    """True if the user wants fleet send / 青铜剑 / 上海运维 / restart agent / 值守检查."""
    haystack = (text or "").lower()
    if not haystack:
        return False
    return any(hint.lower() in haystack for hint in _REMOTE_OPS_HINTS)


def should_block_execute_command(
    *, is_scheduler: bool, user_text: str, command: str
) -> bool:
    """Block local execute_command on the scheduler when the user asked for remote ops."""
    del command  # signature reserved for callers; intent is keyed off user_text
    return bool(is_scheduler) and remote_ops_intent(user_text)
