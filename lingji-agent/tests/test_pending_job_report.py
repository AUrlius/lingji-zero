"""重启后补报 — 落盘 sidecar 与启动 flush。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lingji_agent.execution.pending_job_report import (
    clear_pending,
    flush_pending_report,
    load_pending,
    should_defer_report,
    write_pending,
)


def test_defer_only_self_killing_playbook():
    assert should_defer_report("agent.restart") is True
    assert should_defer_report("agent.status") is False
    assert should_defer_report("fleet-smoke") is False
    assert should_defer_report("") is False


def test_write_load_clear(tmp_path: Path):
    write_pending(
        tmp_path,
        job_id="LJ-TEST1",
        step_id="LJ-TEST1-S1",
        playbook_id="agent.restart",
        evidence={"git_pull": "ok"},
    )
    pending = load_pending(tmp_path)
    assert pending is not None
    assert pending["job_id"] == "LJ-TEST1"
    assert pending["step_id"] == "LJ-TEST1-S1"
    assert pending["playbook_id"] == "agent.restart"
    assert pending["status"] == "completed"
    assert pending["evidence"]["git_pull"] == "ok"
    clear_pending(tmp_path)
    assert load_pending(tmp_path) is None


def test_load_missing_is_none(tmp_path: Path):
    assert load_pending(tmp_path) is None


def test_load_corrupt_is_none_and_cleared(tmp_path: Path):
    sidecar = tmp_path / "pending_job_report.json"
    sidecar.write_text("{not json", encoding="utf-8")
    assert load_pending(tmp_path) is None
    assert not sidecar.exists()


@pytest.mark.asyncio
async def test_flush_no_sidecar_does_not_report(tmp_path: Path):
    calls: list[tuple] = []

    async def reporter(job_id, step_id, *, status, evidence=None, error=""):
        calls.append((job_id, step_id, status, evidence, error))
        return {"job_id": job_id}

    out = await flush_pending_report(tmp_path, reporter=reporter)
    assert out["skipped"] is True
    assert calls == []


@pytest.mark.asyncio
async def test_flush_reports_then_clears(tmp_path: Path):
    write_pending(
        tmp_path,
        job_id="LJ-OK",
        step_id="LJ-OK-S1",
        playbook_id="agent.restart",
        evidence={"git_pull": "ok"},
    )
    calls: list[dict] = []

    async def reporter(job_id, step_id, *, status, evidence=None, error=""):
        calls.append({
            "job_id": job_id,
            "step_id": step_id,
            "status": status,
            "evidence": evidence,
            "error": error,
        })
        return {"job_id": job_id, "status": status}

    out = await flush_pending_report(tmp_path, reporter=reporter)
    assert out["ok"] is True
    assert out["job_id"] == "LJ-OK"
    assert len(calls) == 1
    assert calls[0]["job_id"] == "LJ-OK"
    assert calls[0]["step_id"] == "LJ-OK-S1"
    assert calls[0]["status"] == "completed"
    assert calls[0]["evidence"]["git_pull"] == "ok"
    assert calls[0]["evidence"]["post_restart"] is True
    assert load_pending(tmp_path) is None


@pytest.mark.asyncio
async def test_flush_keeps_sidecar_on_report_error(tmp_path: Path):
    write_pending(
        tmp_path,
        job_id="LJ-KEEP",
        step_id="LJ-KEEP-S1",
        playbook_id="agent.restart",
    )

    async def reporter(job_id, step_id, *, status, evidence=None, error=""):
        return {"error": "gateway down"}

    out = await flush_pending_report(tmp_path, reporter=reporter)
    assert out["ok"] is False
    assert out["kept"] is True
    pending = load_pending(tmp_path)
    assert pending is not None
    assert pending["job_id"] == "LJ-KEEP"


@pytest.mark.asyncio
async def test_flush_skips_incomplete_sidecar(tmp_path: Path):
    (tmp_path / "pending_job_report.json").write_text(
        '{"playbook_id":"agent.restart"}',
        encoding="utf-8",
    )
    calls: list = []

    async def reporter(*args, **kwargs):
        calls.append(1)
        return {}

    out = await flush_pending_report(tmp_path, reporter=reporter)
    assert out["skipped"] is True
    assert calls == []
    assert load_pending(tmp_path) is None
