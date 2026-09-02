import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from lingji_agent.execution.coding_lead import (
    CursorPlanLeadRuntime,
    FakeLeadRuntime,
    LeadDecision,
    compose_executor_prompt,
    lead_cmd_is_safe,
    make_lead_runtime,
    run_coding_with_lead,
    write_executor_prompt,
    write_lead_artifact,
)
from lingji_agent.foundation.config import CodingConfig


def _ok_cli(job_dir):
    return {
        "ok": True,
        "reason": "ok",
        "exit_code": 0,
        "evidence": {"reason": "ok", "runner": "cursor"},
    }


def _need_cli(job_dir):
    q = job_dir / "out" / "questions.md"
    q.parent.mkdir(parents=True, exist_ok=True)
    q.write_text("Please choose A or B", encoding="utf-8")
    return {
        "ok": False,
        "reason": "needs_input",
        "exit_code": -1,
        "evidence": {"reason": "needs_input"},
    }


def test_lead_cmd_rejects_force_and_yolo():
    assert lead_cmd_is_safe(None) is False
    assert lead_cmd_is_safe([]) is False
    assert lead_cmd_is_safe(["/bin/agent", "-p", "--trust"]) is True
    assert lead_cmd_is_safe(["/bin/agent", "-p", "--force", "--trust"]) is False
    assert lead_cmd_is_safe(["/bin/agent", "--YOLO"]) is False
    assert lead_cmd_is_safe(["/bin/agent", "--force=true"]) is False
    assert lead_cmd_is_safe(["/bin/agent", "--sandbox", "disabled"]) is True


def test_write_lead_artifact_only_under_lead(tmp_path: Path):
    job = tmp_path / "LJ-00C0DE01"
    (job / "workspace").mkdir(parents=True)
    path = write_lead_artifact(job, "plan.md", "# plan\nuse python\n")
    assert path == (job / "lead" / "plan.md").resolve()
    assert path.read_text(encoding="utf-8") == "# plan\nuse python\n"
    assert not (job / "workspace" / "plan.md").exists()
    write_lead_artifact(job, "decisions.md", "round1")
    write_lead_artifact(job, "decisions.md", "round2", append=True)
    text = (job / "lead" / "decisions.md").read_text(encoding="utf-8")
    assert "round1" in text and "round2" in text
    with pytest.raises(ValueError):
        write_lead_artifact(job, "notes.md", "no")
    with pytest.raises(ValueError):
        write_lead_artifact(job, "../workspace/hack.py", "no")


def test_compose_and_write_executor_prompt(tmp_path: Path):
    job = tmp_path / "LJ-00C0DE01"
    job.mkdir()
    (job / "brief.md").write_text("write hello", encoding="utf-8")
    write_lead_artifact(job, "plan.md", "create hello.txt")
    dest = write_executor_prompt(job)
    assert dest == job / "executor_prompt.md"
    body = dest.read_text(encoding="utf-8")
    assert "write hello" in body
    assert "## 领队方案" in body
    assert "create hello.txt" in body
    assert "Stay inside the current workspace directory." in body
    assert not (job / "workspace" / "executor_prompt.md").exists()
    prompt = compose_executor_prompt(
        brief="b", plan="p", decisions="choose A"
    )
    assert "## 领队批复" in prompt and "choose A" in prompt


@pytest.mark.asyncio
async def test_fake_lead_runtime_records_timeouts(tmp_path: Path):
    lead = FakeLeadRuntime(
        plan="ship hello.txt",
        decisions=[LeadDecision(ok=True, text="pick A")],
    )
    plan = await lead.propose_plan(job_dir=tmp_path, brief="hi", timeout_sec=12.5)
    assert plan.ok is True
    assert plan.text == "ship hello.txt"
    assert lead.propose_timeouts == [12.5]
    d = await lead.decide(job_dir=tmp_path, questions="A or B?", timeout_sec=9)
    assert d.ok is True and d.text == "pick A"
    assert lead.decide_calls == 1
    empty = FakeLeadRuntime(plan="  ")
    missing = await empty.propose_plan(job_dir=tmp_path, brief="x", timeout_sec=1)
    assert missing.ok is False and missing.reason == "lead_plan_missing"
    assert not (tmp_path / "workspace").exists() or not any(
        (tmp_path / "workspace").iterdir()
    )


@pytest.mark.asyncio
async def test_plan_written_before_executor(tmp_path: Path):
    job = tmp_path / "LJ-A8600691"
    job.mkdir()
    (job / "brief.md").write_text("write hello", encoding="utf-8")
    order = []

    async def run_cli(**kwargs):
        order.append("cli")
        assert (job / "lead" / "plan.md").read_text(encoding="utf-8") == "create hello.txt"
        assert "create hello.txt" in (job / "executor_prompt.md").read_text(encoding="utf-8")
        assert not (job / "workspace" / "plan.md").exists()
        return _ok_cli(job)

    lead = FakeLeadRuntime(plan="create hello.txt")
    result = await run_coding_with_lead(
        job_dir=job,
        brief="write hello",
        lead=lead,
        run_cli=run_cli,
        start_cmd=["/usr/bin/true"],
        timeout_sec=100,
        hung_sec=90,
        heartbeat_sec=15,
        progress_sec=30,
        lead_round_timeout_sec=20,
    )
    assert result["reason"] == "ok"
    assert order == ["cli"]
    assert lead.propose_timeouts == [20]


@pytest.mark.asyncio
async def test_empty_plan_skips_executor(tmp_path: Path):
    job = tmp_path / "LJ-A8600691"
    job.mkdir()
    run_cli = AsyncMock()
    result = await run_coding_with_lead(
        job_dir=job,
        brief="x",
        lead=FakeLeadRuntime(plan=""),
        run_cli=run_cli,
        start_cmd=["/usr/bin/true"],
        timeout_sec=50,
        hung_sec=90,
        heartbeat_sec=15,
        progress_sec=30,
    )
    assert result["ok"] is False
    assert result["reason"] == "lead_plan_missing"
    run_cli.assert_not_called()


@pytest.mark.asyncio
async def test_three_question_rounds_then_ok(tmp_path: Path):
    job = tmp_path / "LJ-A8600691"
    job.mkdir()
    (job / "brief.md").write_text("b", encoding="utf-8")
    n = {"cli": 0}

    async def run_cli(**kwargs):
        n["cli"] += 1
        if n["cli"] <= 3:
            return _need_cli(job)
        return _ok_cli(job)

    lead = FakeLeadRuntime(
        plan="p",
        decisions=[
            LeadDecision(ok=True, text="A"),
            LeadDecision(ok=True, text="B"),
            LeadDecision(ok=True, text="C"),
        ],
    )
    result = await run_coding_with_lead(
        job_dir=job,
        brief="b",
        lead=lead,
        run_cli=run_cli,
        start_cmd=["/usr/bin/true"],
        timeout_sec=100,
        hung_sec=90,
        heartbeat_sec=15,
        progress_sec=30,
    )
    assert result["reason"] == "ok"
    assert n["cli"] == 4
    assert lead.decide_calls == 3
    dec = (job / "lead" / "decisions.md").read_text(encoding="utf-8")
    assert "A" in dec and "C" in dec


@pytest.mark.asyncio
async def test_fourth_question_fails_needs_input(tmp_path: Path):
    job = tmp_path / "LJ-A8600691"
    job.mkdir()
    (job / "brief.md").write_text("b", encoding="utf-8")

    async def run_cli(**kwargs):
        return _need_cli(job)

    lead = FakeLeadRuntime(
        plan="p",
        decisions=[LeadDecision(ok=True, text=x) for x in "ABC"],
    )
    result = await run_coding_with_lead(
        job_dir=job,
        brief="b",
        lead=lead,
        run_cli=run_cli,
        start_cmd=["/usr/bin/true"],
        timeout_sec=100,
        hung_sec=90,
        heartbeat_sec=15,
        progress_sec=30,
    )
    assert result["ok"] is False
    assert result["reason"] == "needs_input"
    assert lead.decide_calls == 3


@pytest.mark.asyncio
async def test_lead_reject_stops_without_rerun(tmp_path: Path):
    job = tmp_path / "LJ-A8600691"
    job.mkdir()
    (job / "brief.md").write_text("b", encoding="utf-8")
    n = {"cli": 0}

    async def run_cli(**kwargs):
        n["cli"] += 1
        return _need_cli(job)

    lead = FakeLeadRuntime(
        plan="p",
        decisions=[LeadDecision(ok=False, text="", reason="needs_input")],
    )
    result = await run_coding_with_lead(
        job_dir=job,
        brief="b",
        lead=lead,
        run_cli=run_cli,
        start_cmd=["/usr/bin/true"],
        timeout_sec=100,
        hung_sec=90,
        heartbeat_sec=15,
        progress_sec=30,
    )
    assert result["reason"] == "needs_input"
    assert n["cli"] == 1
    assert lead.decide_calls == 1


@pytest.mark.asyncio
async def test_cursor_plan_lead_cwd_is_lead_not_workspace(tmp_path: Path):
    job = tmp_path / "LJ-LEAD0001"
    (job / "workspace").mkdir(parents=True)
    script = tmp_path / "lead.py"
    script.write_text(
        "import os, pathlib\n"
        "print('PLAN:' + os.getcwd())\n"
        "pathlib.Path('marker.txt').write_text('lead', encoding='utf-8')\n",
        encoding="utf-8",
    )
    rt = CursorPlanLeadRuntime(
        [sys.executable, "-u", str(script)],
        hung_sec=5,
        heartbeat_sec=0.05,
        progress_sec=10,
    )
    decision = await rt.propose_plan(job_dir=job, brief="b", timeout_sec=5)
    assert decision.ok is True
    assert str((job / "lead").resolve()) in decision.text.replace("\\", "/")
    assert (job / "lead" / "marker.txt").is_file()
    assert not (job / "workspace" / "marker.txt").exists()


def test_make_lead_runtime_none_when_empty_or_force():
    assert make_lead_runtime(CodingConfig(lead_cmd=[])) is None
    assert make_lead_runtime(CodingConfig(lead_cmd=["agent", "--force"])) is None
    rt = make_lead_runtime(CodingConfig(lead_cmd=["/bin/agent", "-p", "--trust"]))
    assert isinstance(rt, CursorPlanLeadRuntime)


@pytest.mark.asyncio
async def test_cursor_plan_lead_rejects_force_cmd(tmp_path: Path):
    rt = CursorPlanLeadRuntime(["/bin/agent", "--force"])
    d = await rt.propose_plan(job_dir=tmp_path, brief="b", timeout_sec=1)
    assert d.ok is False and d.reason == "runner_missing"
