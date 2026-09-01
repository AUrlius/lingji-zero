"""机要控制面 — CMD_HERMES_SESSION（不进 LangGraph / 秘书聊天）。

本切片：health 尽力探测进程；start/stop 不拉起、不杀掉飞书 Hermes，
避免假在线。右栏入站会话仍待 4.0d-4。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

UNIMPLEMENTED_REASON = (
    "本切片不拉起 Hermes 进程，右栏通道未接通。"
    "破窗请用飞书/Telegram 原生 Hermes。"
)
CHANNEL_NOT_READY = "进程在跑，入站通道未接通。"

_HERMES_PROCESS_NAMES = ("hermes", "openclaw")


def probe_hermes_running() -> bool:
    """pgrep -x 常见进程名；找不到或不可用则视为未运行。"""
    pgrep = shutil.which("pgrep")
    if not pgrep:
        return False
    for name in _HERMES_PROCESS_NAMES:
        try:
            result = subprocess.run(
                [pgrep, "-x", name],
                capture_output=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return True
    return False


def handle_hermes_session(
    action: str,
    *,
    probe: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """返回写入 AGENT_RES.payload 的字段（调用方再补 status/target_*）。"""
    act = (action or "health").strip().lower()
    if act not in ("start", "stop", "health"):
        act = "health"
    probe_fn = probe or probe_hermes_running
    running = False
    try:
        running = bool(probe_fn())
    except Exception as exc:
        logger.warning("hermes health probe failed: %s", exc)
        running = False

    if act == "health":
        return {
            "action": "health",
            "unimplemented": False,
            "hermes_status": "online" if running else "off",
            "channel_ready": False,
            "reason": CHANNEL_NOT_READY if running else UNIMPLEMENTED_REASON,
        }

    # start/stop：本切片不改进程，也不把 start 报成在线。
    return {
        "action": act,
        "unimplemented": True,
        "hermes_status": "off",
        "channel_ready": False,
        "reason": UNIMPLEMENTED_REASON,
    }
