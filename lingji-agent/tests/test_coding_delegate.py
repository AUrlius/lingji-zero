"""handle_job_delegate + startup orphan recover — Fleet 4.0e Task 12."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from lingji_agent.execution.approval_scope import default_coding_scope
from lingji_agent.execution.coding_lead import FakeLeadRuntime, LeadDecision
from lingji_agent.execution.coding_supervisor import (
    handle_job_delegate,
    recover_orphan_coding_jobs,
)
from lingji_agent.foundation.config import CodingConfig


def _lead() -> FakeLeadRuntime:
    return FakeLeadRuntime(plan="ok plan")


def _payload(**over) -> dict:
    data = {
        "job_id": "LJ-ABCD1234",
        "step_id": "s1",
        "playbook_id": "coding.cursor",
        "brief": "write hello.txt",
        "runner": "cursor",
        "source_git": "",
        "timeout_sec": 60,
        "approval_scope": default_coding_scope(),
    }
    data.update(over)
    return data


def _cfg(tmp_path: Path, **over) -> CodingConfig:
    kw = {
        "jobs_root": str(tmp_path),
        "start_cmd": ["/usr/bin/true"],
        "timeout_sec": 1800,
        "timeout_hard_sec": 3600,
        "hung_sec": 180,
        "heartbeat_sec": 15,
        "progress_sec": 30,
        "source_git_allowlist": [],
    }
    kw.update(over)
    return CodingConfig(**kw)


def _ok_cli_result(job_dir: Path | None = None) -> dict:
    workspace = str((job_dir or Path(".")) / "workspace")
    return {
        "ok": True,
        "reason": "ok",
        "exit_code": 0,
        "evidence": {
            "runner": "cursor",
            "workspace": workspace,
            "exit_code": 0,
            "reason": "ok",
            "log_tail": "",
            "summary": "done",
        },
    }


@pytest.mark.asyncio
async def test_empty_start_cmd_reports_runner_missing(tmp_path: Path):
    report = AsyncMock()
    await handle_job_delegate(
        _payload(),
        _cfg(tmp_path, start_cmd=[]),
        report=report,
    )
    report.assert_awaited()
    job_id, step_id = report.await_args.args[:2]
    kwargs = report.await_args.kwargs
    assert job_id == "LJ-ABCD1234"
    assert step_id == "s1"
    assert kwargs["status"] == "failed"
    assert kwargs["evidence"]["reason"] == "runner_missing"
    assert kwargs["error"]
    assert report.await_count == 1


@pytest.mark.asyncio
async def test_empty_jobs_root_reports_runner_missing(tmp_path: Path):
    report = AsyncMock()
    await handle_job_delegate(
        _payload(),
        _cfg(tmp_path, jobs_root=""),
        report=report,
    )
    kwargs = report.await_args.kwargs
    assert kwargs["status"] == "failed"
    assert kwargs["evidence"]["reason"] == "runner_missing"


@pytest.mark.asyncio
async def test_non_coding_playbook_does_not_report(tmp_path: Path):
    report = AsyncMock()
    await handle_job_delegate(
        _payload(playbook_id="agent.status"),
        _cfg(tmp_path),
        report=report,
    )
    report.assert_not_called()


@pytest.mark.asyncio
async def test_fake_success_reports_completed(tmp_path: Path):
    report = AsyncMock()
    fake_cli = AsyncMock(return_value=_ok_cli_result(tmp_path / "LJ-ABCD1234"))
    with patch(
        "lingji_agent.execution.coding_supervisor.run_coding_cli",
        fake_cli,
    ):
        await handle_job_delegate(
            _payload(), _cfg(tmp_path), report=report, lead_runtime=_lead()
        )

    fake_cli.assert_awaited()
    kwargs = report.await_args.kwargs
    assert kwargs["status"] == "completed"
    assert kwargs["evidence"]["reason"] == "ok"
    assert not (tmp_path / ".coding_lock").exists()
    assert (tmp_path / "LJ-ABCD1234" / "brief.md").read_text(encoding="utf-8") == (
        "write hello.txt"
    )


@pytest.mark.asyncio
async def test_handle_job_delegate_second_job_executor_busy(tmp_path: Path):
    """Second overlapping JOB_DELEGATE must fail immediately, not queue."""
    started = asyncio.Event()
    release = asyncio.Event()
    cli_calls = 0
    reports: list[tuple[str, str, str, str]] = []

    async def report(job_id, step_id, *, status, evidence=None, error=""):
        reports.append(
            (job_id, status, str(error or ""), str((evidence or {}).get("reason") or ""))
        )

    async def fake_cli(**kwargs):
        nonlocal cli_calls
        cli_calls += 1
        started.set()
        await release.wait()
        return _ok_cli_result(kwargs.get("job_dir"))

    with patch(
        "lingji_agent.execution.coding_supervisor.run_coding_cli",
        fake_cli,
    ):
        first = asyncio.create_task(
            handle_job_delegate(
                _payload(job_id="LJ-AAAA0001"),
                _cfg(tmp_path),
                report=report,
                lead_runtime=_lead(),
            )
        )
        await asyncio.wait_for(started.wait(), timeout=2)
        second = asyncio.create_task(
            handle_job_delegate(
                _payload(job_id="LJ-BBBB0001"),
                _cfg(tmp_path),
                report=report,
                lead_runtime=_lead(),
            )
        )
        done, _pending = await asyncio.wait({second}, timeout=0.5)
        assert second in done, "second job queued behind first instead of failing immediately"
        await second
        release.set()
        await first

    assert cli_calls == 1
    by_id = {job_id: (status, error, reason) for job_id, status, error, reason in reports}
    assert by_id["LJ-AAAA0001"][0] == "completed"
    assert by_id["LJ-BBBB0001"][0] == "failed"
    assert by_id["LJ-BBBB0001"][2] == "executor_busy"
    assert not (tmp_path / ".coding_lock").exists()


@pytest.mark.asyncio
async def test_progress_reports_are_awaited_before_delegate_returns(tmp_path: Path):
    """create_task progress reports must be retained and finished before concluding."""
    progress_started = asyncio.Event()
    progress_release = asyncio.Event()
    statuses: list[str] = []

    async def report(job_id, step_id, *, status, evidence=None, error=""):
        statuses.append(status)
        if status == "progress":
            progress_started.set()
            await progress_release.wait()

    async def fake_cli(*, on_progress, job_dir, **kwargs):
        on_progress({"reason": "progress"})
        await progress_started.wait()
        return _ok_cli_result(job_dir)

    with patch(
        "lingji_agent.execution.coding_supervisor.run_coding_cli",
        fake_cli,
    ):
        delegate = asyncio.create_task(
            handle_job_delegate(
                _payload(), _cfg(tmp_path), report=report, lead_runtime=_lead()
            )
        )
        await asyncio.wait_for(progress_started.wait(), timeout=2)
        await asyncio.sleep(0.05)
        assert not delegate.done(), "delegate returned before progress report finished"
        assert "completed" not in statuses
        progress_release.set()
        await asyncio.wait_for(delegate, timeout=2)

    assert statuses[0] == "progress"
    assert statuses[-1] == "completed"


@pytest.mark.asyncio
async def test_cli_failure_reports_failed(tmp_path: Path):
    report = AsyncMock()
    fake_cli = AsyncMock(
        return_value={
            "ok": False,
            "reason": "crash",
            "exit_code": 7,
            "evidence": {"reason": "crash", "runner": "cursor", "exit_code": 7},
        }
    )
    with patch(
        "lingji_agent.execution.coding_supervisor.run_coding_cli",
        fake_cli,
    ):
        await handle_job_delegate(
            _payload(), _cfg(tmp_path), report=report, lead_runtime=_lead()
        )
    kwargs = report.await_args.kwargs
    assert kwargs["status"] == "failed"
    assert kwargs["error"] == "crash"
    assert kwargs["evidence"]["reason"] == "crash"


@pytest.mark.asyncio
async def test_brief_missing_after_get_job(tmp_path: Path):
    report = AsyncMock()
    get_job = AsyncMock(return_value={"job_id": "LJ-ABCD1234", "plan": {}})
    fake_cli = AsyncMock()
    with patch(
        "lingji_agent.execution.coding_supervisor.run_coding_cli",
        fake_cli,
    ):
        await handle_job_delegate(
            _payload(brief=""),
            _cfg(tmp_path),
            report=report,
            get_job=get_job,
        )
    get_job.assert_awaited()
    kwargs = report.await_args.kwargs
    assert kwargs["status"] == "failed"
    assert kwargs["evidence"]["reason"] == "brief_missing"
    fake_cli.assert_not_called()


@pytest.mark.asyncio
async def test_get_job_fills_brief_then_completed(tmp_path: Path):
    report = AsyncMock()
    get_job = AsyncMock(
        return_value={"plan": {"brief": "from gateway"}}
    )
    fake_cli = AsyncMock(return_value=_ok_cli_result(tmp_path / "LJ-ABCD1234"))
    with patch(
        "lingji_agent.execution.coding_supervisor.run_coding_cli",
        fake_cli,
    ):
        await handle_job_delegate(
            _payload(brief=""),
            _cfg(tmp_path),
            report=report,
            get_job=get_job,
            lead_runtime=_lead(),
        )
    get_job.assert_awaited_with("LJ-ABCD1234")
    assert report.await_args.kwargs["status"] == "completed"
    assert (tmp_path / "LJ-ABCD1234" / "brief.md").read_text(encoding="utf-8") == (
        "from gateway"
    )


@pytest.mark.asyncio
async def test_missing_lead_cmd_reports_runner_missing(tmp_path: Path):
    report = AsyncMock()
    fake_cli = AsyncMock()
    with patch(
        "lingji_agent.execution.coding_supervisor.run_coding_cli",
        fake_cli,
    ):
        await handle_job_delegate(_payload(), _cfg(tmp_path), report=report)
    kwargs = report.await_args.kwargs
    assert kwargs["status"] == "failed"
    assert kwargs["evidence"]["reason"] == "runner_missing"
    assert "lead_cmd" in (kwargs["error"] or "")
    fake_cli.assert_not_called()


@pytest.mark.asyncio
async def test_delegate_needs_input_then_lead_then_completed(tmp_path: Path):
    report = AsyncMock()
    n = {"cli": 0}

    async def fake_cli(*, job_dir, **kwargs):
        n["cli"] += 1
        if n["cli"] == 1:
            q = job_dir / "out" / "questions.md"
            q.parent.mkdir(parents=True, exist_ok=True)
            q.write_text("Please choose A", encoding="utf-8")
            return {
                "ok": False,
                "reason": "needs_input",
                "exit_code": -1,
                "evidence": {"reason": "needs_input"},
            }
        return _ok_cli_result(job_dir)

    lead = FakeLeadRuntime(
        plan="use python",
        decisions=[LeadDecision(ok=True, text="A")],
    )
    with patch(
        "lingji_agent.execution.coding_supervisor.run_coding_cli",
        fake_cli,
    ):
        await handle_job_delegate(
            _payload(), _cfg(tmp_path), report=report, lead_runtime=lead
        )
    kwargs = report.await_args.kwargs
    assert kwargs["status"] == "completed"
    assert n["cli"] == 2
    job_dir = tmp_path / "LJ-ABCD1234"
    assert "use python" in (job_dir / "lead" / "plan.md").read_text(encoding="utf-8")
    assert "A" in (job_dir / "lead" / "decisions.md").read_text(encoding="utf-8")



def _orphan_dir(
    tmp_path: Path,
    *,
    job_id: str = "LJ-DEADBEEF",
    pid: str = "2147483647",
    heartbeat_fresh: bool = False,
) -> Path:
    job = tmp_path / job_id
    job.mkdir()
    (job / "logs").mkdir()
    (job / "out").mkdir()
    (job / "workspace").mkdir()
    (job / "meta.json").write_text(
        json.dumps({"job_id": job_id, "step_id": "s1", "runner": "cursor"}),
        encoding="utf-8",
    )
    (job / ".pid").write_text(pid, encoding="utf-8")
    hb = job / "logs" / "heartbeat"
    hb.write_text("2026-01-01T00:00:00Z", encoding="utf-8")
    if not heartbeat_fresh:
        old = time.time() - 10_000
        os.utime(hb, (old, old))
    return job


@pytest.mark.asyncio
async def test_recover_orphan_reports_executor_lost(tmp_path: Path):
    _orphan_dir(tmp_path)
    report = AsyncMock()
    items = await recover_orphan_coding_jobs(tmp_path, report=report)
    assert len(items) == 1
    report.assert_awaited()
    kwargs = report.await_args.kwargs
    assert report.await_args.args[0] == "LJ-DEADBEEF"
    assert report.await_args.args[1] == "s1"
    assert kwargs["status"] == "failed"
    assert kwargs["error"] == "executor_lost"
    assert kwargs["evidence"]["reason"] == "executor_lost"


@pytest.mark.asyncio
async def test_recover_kills_only_when_heartbeat_stale(tmp_path: Path):
    live = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    stale = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        _orphan_dir(
            tmp_path,
            job_id="LJ-AAAA0001",
            pid=str(live.pid),
            heartbeat_fresh=True,
        )
        _orphan_dir(
            tmp_path,
            job_id="LJ-BBBB0001",
            pid=str(stale.pid),
            heartbeat_fresh=False,
        )
        report = AsyncMock()
        items = await recover_orphan_coding_jobs(tmp_path, report=report, hung_sec=180)
        lost_ids = {item["job_id"] for item in items}
        assert "LJ-BBBB0001" in lost_ids
        assert "LJ-AAAA0001" not in lost_ids
        stale.wait(timeout=2)
        assert stale.poll() is not None
        assert live.poll() is None
        assert report.await_count == 1
        assert report.await_args.args[0] == "LJ-BBBB0001"
    finally:
        for proc in (live, stale):
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=2)
