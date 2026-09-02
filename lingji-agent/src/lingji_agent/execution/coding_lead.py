"""coding_run 领队 — Fleet 4.0f。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_ALLOWED_LEAD_NAMES = frozenset({"plan.md", "decisions.md"})


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


def write_lead_artifact(
    job_dir: Path, name: str, text: str, *, append: bool = False
) -> Path:
    if name not in _ALLOWED_LEAD_NAMES:
        raise ValueError(f"invalid lead artifact name: {name!r}")
    lead_root = (Path(job_dir) / "lead").resolve()
    lead_root.mkdir(parents=True, exist_ok=True)
    dest = (lead_root / name).resolve()
    if dest.parent != lead_root:
        raise ValueError(f"lead artifact escapes lead directory: {name!r}")
    if append and dest.exists():
        existing = dest.read_text(encoding="utf-8")
        content = existing + "\n\n" + text
    else:
        content = text
    dest.write_text(content, encoding="utf-8")
    return dest


@dataclass
class LeadDecision:
    ok: bool
    text: str
    reason: str = ""


class LeadRuntime(Protocol):
    async def propose_plan(
        self, *, job_dir: Path, brief: str, timeout_sec: float
    ) -> LeadDecision: ...

    async def decide(
        self, *, job_dir: Path, questions: str, timeout_sec: float
    ) -> LeadDecision: ...


class FakeLeadRuntime:
    def __init__(
        self,
        plan: str = "use python",
        decisions: list[LeadDecision] | None = None,
    ) -> None:
        self._plan = plan
        self._decisions = list(decisions) if decisions is not None else []
        self.propose_timeouts: list[float] = []
        self.decide_calls = 0

    async def propose_plan(
        self, *, job_dir: Path, brief: str, timeout_sec: float
    ) -> LeadDecision:
        self.propose_timeouts.append(timeout_sec)
        if self._plan.strip():
            return LeadDecision(ok=True, text=self._plan, reason="")
        return LeadDecision(ok=False, text=self._plan, reason="lead_plan_missing")

    async def decide(
        self, *, job_dir: Path, questions: str, timeout_sec: float
    ) -> LeadDecision:
        self.decide_calls += 1
        if not self._decisions:
            return LeadDecision(ok=False, text="", reason="needs_input")
        return self._decisions.pop(0)


def compose_executor_prompt(
    *, brief: str, plan: str, decisions: str = ""
) -> str:
    parts = [brief, "", "## 领队方案", "", plan]
    if decisions:
        parts.extend(["", "## 领队批复", "", decisions])
    parts.extend(["", "Stay inside the current workspace directory."])
    return "\n".join(parts)


def write_executor_prompt(job_dir: Path) -> Path:
    job = Path(job_dir)
    brief_path = job / "brief.md"
    brief = brief_path.read_text(encoding="utf-8") if brief_path.exists() else ""
    plan_path = (job / "lead" / "plan.md").resolve()
    plan = plan_path.read_text(encoding="utf-8") if plan_path.exists() else ""
    decisions_path = (job / "lead" / "decisions.md").resolve()
    decisions = (
        decisions_path.read_text(encoding="utf-8")
        if decisions_path.exists()
        else ""
    )
    content = compose_executor_prompt(brief=brief, plan=plan, decisions=decisions)
    dest = job / "executor_prompt.md"
    dest.write_text(content, encoding="utf-8")
    return dest


def _early_fail(reason: str) -> dict:
    return {
        "ok": False,
        "reason": reason,
        "exit_code": None,
        "evidence": {"reason": reason},
    }


async def run_coding_with_lead(
    *,
    job_dir: Path,
    brief: str,
    lead: LeadRuntime,
    run_cli,
    start_cmd: list[str],
    timeout_sec: float,
    hung_sec: float,
    heartbeat_sec: float,
    progress_sec: float,
    on_progress=None,
    lead_round_timeout_sec: float = 1200,
    lead_max_question_rounds: int = 3,
    clock=None,
) -> dict:
    job_dir = Path(job_dir)
    now = clock if clock is not None else time.monotonic
    deadline = now() + float(timeout_sec)

    def remaining() -> float:
        return deadline - now()

    rem = remaining()
    if rem <= 0:
        return _early_fail("timeout")

    lead_round = min(float(lead_round_timeout_sec), rem)
    plan_decision = await lead.propose_plan(
        job_dir=job_dir, brief=brief, timeout_sec=lead_round
    )
    if not (plan_decision.ok and plan_decision.text.strip()):
        reason = plan_decision.reason or "lead_plan_missing"
        return _early_fail(reason)

    write_lead_artifact(job_dir, "plan.md", plan_decision.text)
    write_executor_prompt(job_dir)

    questions_seen = 0
    while True:
        rem = remaining()
        if rem <= 0:
            return _early_fail("timeout")

        result = await run_cli(
            job_dir=job_dir,
            start_cmd=start_cmd,
            timeout_sec=rem,
            hung_sec=hung_sec,
            heartbeat_sec=heartbeat_sec,
            progress_sec=progress_sec,
            on_progress=on_progress,
        )
        if result.get("reason") != "needs_input":
            return result

        questions_seen += 1
        if questions_seen > lead_max_question_rounds:
            return result

        rem = remaining()
        if rem <= 0:
            return _early_fail("timeout")

        q_path = job_dir / "out" / "questions.md"
        questions = q_path.read_text(encoding="utf-8") if q_path.exists() else ""
        decide_timeout = min(float(lead_round_timeout_sec), rem)
        decision = await lead.decide(
            job_dir=job_dir, questions=questions, timeout_sec=decide_timeout
        )
        if not decision.ok:
            reason = decision.reason or "needs_input"
            return _early_fail(reason)

        write_lead_artifact(job_dir, "decisions.md", decision.text, append=True)
        write_executor_prompt(job_dir)
