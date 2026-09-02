from pathlib import Path

import pytest

from lingji_agent.execution.coding_lead import (
    FakeLeadRuntime,
    LeadDecision,
    compose_executor_prompt,
    lead_cmd_is_safe,
    write_executor_prompt,
    write_lead_artifact,
)


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
