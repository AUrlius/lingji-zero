"""档 A playbook runner — 未知 id / 缺脚本 / 成功脚本。"""

from __future__ import annotations

import shutil

import pytest

from lingji_agent.execution.playbook_runner import PLAYBOOK_SCRIPTS, run_playbook, script_for
from lingji_agent.execution.tools.job_tools import job_invoke


def test_known_playbook_ids():
    assert set(PLAYBOOK_SCRIPTS) == {
        "agent.status",
        "agent.restart",
        "git-pull-deploy",
        "fleet-smoke",
    }


def test_unknown_playbook_script_none():
    assert script_for("not-a-playbook") is None


@pytest.mark.asyncio
async def test_run_unknown_playbook():
    result = await run_playbook("not-a-playbook")
    assert result["ok"] is False
    assert "unknown playbook" in result["error"]


@pytest.mark.asyncio
async def test_run_missing_script(tmp_path, monkeypatch):
    monkeypatch.setenv("LINGJI_REPO_ROOT", str(tmp_path))
    result = await run_playbook("agent.status")
    assert result["ok"] is False
    assert "missing" in result["error"]


@pytest.mark.asyncio
async def test_run_ok_script(tmp_path, monkeypatch):
    if not shutil.which("bash"):
        pytest.skip("bash required")
    monkeypatch.setenv("LINGJI_REPO_ROOT", str(tmp_path))
    scripts = tmp_path / "scripts" / "playbooks"
    scripts.mkdir(parents=True)
    (scripts / "agent_status.sh").write_text(
        "#!/usr/bin/env bash\necho probe\necho STATUS=ok\n",
        encoding="utf-8",
    )
    result = await run_playbook("agent.status", timeout_sec=10)
    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert "STATUS=ok" in result["stdout"]


@pytest.mark.asyncio
async def test_job_invoke_rejects_unknown_playbook():
    out = await job_invoke(user_id="u1", playbook_id="shell-me")
    assert "error" in out
    assert "未知 playbook" in out["error"]
