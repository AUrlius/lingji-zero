"""档 A：仓库写死 playbook 脚本执行（不接 Hermes CLI / OpenClaw）。"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

PLAYBOOK_SCRIPTS = {
    "agent.status": "agent_status.sh",
    "agent.restart": "agent_restart.sh",
    "git-pull-deploy": "git_pull_deploy.sh",
    "fleet-smoke": "fleet_smoke.sh",
}

DEFAULT_REPO_ROOT = "/mnt/e/LingjiPlan/LingjiZero"
DEFAULT_TIMEOUT_SEC = 120


def repo_root() -> Path:
    return Path(os.getenv("LINGJI_REPO_ROOT", DEFAULT_REPO_ROOT))


def script_for(playbook_id: str) -> Path | None:
    name = PLAYBOOK_SCRIPTS.get(playbook_id or "")
    if not name:
        return None
    return repo_root() / "scripts" / "playbooks" / name


async def run_playbook(playbook_id: str, *, timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> dict:
    script = script_for(playbook_id)
    if script is None:
        return {"ok": False, "error": f"unknown playbook: {playbook_id}"}
    if not script.is_file():
        return {"ok": False, "error": f"playbook script missing: {script}"}
    cwd = repo_root()
    try:
        proc = await asyncio.create_subprocess_exec(
            "bash",
            str(script),
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"playbook timeout ({int(timeout_sec)}s)", "timed_out": True}
    except FileNotFoundError:
        return {"ok": False, "error": "bash not found (need WSL)"}
    stdout = (stdout_b or b"").decode("utf-8", errors="replace")[-4000:]
    stderr = (stderr_b or b"").decode("utf-8", errors="replace")[-2000:]
    ok = proc.returncode == 0 and "STATUS=fail" not in stdout.splitlines()[-1:]
    if stdout.strip().endswith("STATUS=fail") or "STATUS=fail" in stdout[-200:]:
        ok = False
    if "STATUS=ok" in stdout[-400:]:
        ok = proc.returncode == 0
    return {
        "ok": ok,
        "playbook_id": playbook_id,
        "exit_code": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
    }
