"""coding_run 领队 — Fleet 4.0f。"""

from __future__ import annotations

from pathlib import Path

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
