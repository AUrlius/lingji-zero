"""coding_run 领队 — Fleet 4.0f。"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from lingji_agent.execution.hermes_session import argv_list

_ALLOWED_LEAD_NAMES = frozenset({"plan.md", "decisions.md"})
_SUPERVISE_FAIL_REASONS = frozenset({"timeout", "hung", "crash"})


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.exists() and b.exists() and a.samefile(b)
    except OSError:
        return False


def _link_or_skip_brief_run_log(supervise_log: Path, brief_log: Path) -> None:
    """Best-effort hardlink/symlink lead/run.log → logs/run.log before spawn."""
    if _same_file(supervise_log, brief_log):
        return
    if brief_log.exists() or brief_log.is_symlink():
        return
    try:
        brief_log.hardlink_to(supervise_log)
        return
    except OSError:
        pass
    try:
        brief_log.symlink_to(Path("logs") / "run.log")
    except OSError:
        pass


def _ensure_brief_run_log(supervise_log: Path, brief_log: Path) -> None:
    """Ensure brief lead/run.log exists (link if possible, else copy)."""
    if _same_file(supervise_log, brief_log):
        return
    if not supervise_log.is_file():
        return
    if brief_log.exists() or brief_log.is_symlink():
        try:
            brief_log.unlink()
        except OSError:
            pass
    try:
        brief_log.hardlink_to(supervise_log)
        return
    except OSError:
        pass
    try:
        brief_log.symlink_to(Path("logs") / "run.log")
        return
    except OSError:
        pass
    brief_log.write_bytes(supervise_log.read_bytes())


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


class CursorPlanLeadRuntime:
    def __init__(
        self,
        lead_cmd: list[str],
        *,
        hung_sec: float = 900,
        heartbeat_sec: float = 15,
        progress_sec: float = 30,
        spawn=None,
        argv_check=None,
    ) -> None:
        self._lead_cmd = [str(x) for x in (lead_cmd or [])]
        self._hung_sec = float(hung_sec)
        self._heartbeat_sec = float(heartbeat_sec)
        self._progress_sec = float(progress_sec)
        self._spawn = spawn if spawn is not None else subprocess.Popen
        self._argv_check = argv_check if argv_check is not None else argv_list

    async def propose_plan(
        self, *, job_dir: Path, brief: str, timeout_sec: float
    ) -> LeadDecision:
        return await self._run_lead(job_dir=Path(job_dir), timeout_sec=timeout_sec)

    async def decide(
        self, *, job_dir: Path, questions: str, timeout_sec: float
    ) -> LeadDecision:
        job = Path(job_dir)
        lead_dir = job / "lead"
        lead_dir.mkdir(parents=True, exist_ok=True)
        (lead_dir / "questions_in.md").write_text(questions or "", encoding="utf-8")
        return await self._run_lead(job_dir=job, timeout_sec=timeout_sec)

    async def _run_lead(self, *, job_dir: Path, timeout_sec: float) -> LeadDecision:
        if not lead_cmd_is_safe(self._lead_cmd):
            return LeadDecision(ok=False, text="", reason="runner_missing")
        try:
            argv = self._argv_check(self._lead_cmd)
        except (TypeError, ValueError):
            return LeadDecision(ok=False, text="", reason="runner_missing")
        if not argv:
            return LeadDecision(ok=False, text="", reason="runner_missing")

        lead_dir = job_dir / "lead"
        lead_dir.mkdir(parents=True, exist_ok=True)
        # Always write the FD supervise_process watches; mirror brief path lead/run.log.
        logs_dir = lead_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        supervise_log = logs_dir / "run.log"
        brief_log = lead_dir / "run.log"
        if not supervise_log.exists():
            supervise_log.touch()
        _link_or_skip_brief_run_log(supervise_log, brief_log)

        offset = supervise_log.stat().st_size if supervise_log.is_file() else 0
        from lingji_agent.execution.coding_supervisor import supervise_process

        log_f = supervise_log.open("ab")
        try:
            try:
                proc = self._spawn(
                    argv,
                    cwd=str(lead_dir),
                    stdin=subprocess.DEVNULL,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except OSError:
                return LeadDecision(ok=False, text="", reason="runner_missing")

            outcome = await supervise_process(
                proc=proc,
                job_dir=lead_dir,
                timeout_sec=float(timeout_sec),
                hung_sec=self._hung_sec,
                heartbeat_sec=self._heartbeat_sec,
                progress_sec=self._progress_sec,
            )
        finally:
            log_f.close()
            _ensure_brief_run_log(supervise_log, brief_log)

        chunk = b""
        if supervise_log.is_file():
            data = supervise_log.read_bytes()
            chunk = data[offset:] if offset <= len(data) else data
        text = chunk.decode("utf-8", errors="replace").strip()

        if outcome.get("reason") == "ok" and text:
            return LeadDecision(ok=True, text=text, reason="")

        reason = str(outcome.get("reason") or "")
        if reason not in _SUPERVISE_FAIL_REASONS:
            reason = "lead_plan_missing"
        return LeadDecision(ok=False, text=text, reason=reason)


def make_lead_runtime(coding_cfg) -> LeadRuntime | None:
    """Build Cursor lead runtime when lead_cmd is present and safe."""
    lead_cmd = [str(x) for x in (getattr(coding_cfg, "lead_cmd", None) or [])]
    if not lead_cmd or not lead_cmd_is_safe(lead_cmd):
        return None
    return CursorPlanLeadRuntime(
        lead_cmd,
        hung_sec=float(getattr(coding_cfg, "hung_sec", 900) or 900),
        heartbeat_sec=float(getattr(coding_cfg, "heartbeat_sec", 15) or 15),
        progress_sec=float(getattr(coding_cfg, "progress_sec", 30) or 30),
    )


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
