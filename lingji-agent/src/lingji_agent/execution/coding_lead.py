"""coding_run 领队 — Fleet 4.0f。"""

from __future__ import annotations


def lead_cmd_is_safe(cmd: list[str] | None) -> bool:
    if not cmd:
        return False
    for part in cmd:
        token = str(part).strip().lower()
        if token == "--force" or token == "--yolo":
            return False
        if token.startswith("--force") or token.startswith("--yolo"):
            return False
    return True
