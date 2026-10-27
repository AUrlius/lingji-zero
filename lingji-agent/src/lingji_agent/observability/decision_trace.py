"""One run, one replayable decision trace.

Local JSON is always written. LangSmith receives the same public fields only
when ``observability.langsmith_enabled`` is on and ``LANGSMITH_API_KEY`` is set.
That flag (or ``LINGJI_LANGSMITH_ENABLED``) is the only switch. A missing key
keeps the local trace and does not raise.

Outward records drop secrets, account ids, and raw private text.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_CURRENT: ContextVar[DecisionTrace | None] = ContextVar(
    "lingji_decision_trace",
    default=None,
)

_SAFE_LABEL = re.compile(r"^[A-Za-z0-9._:\-]{1,64}$")
_SECRET = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_\-]{6,}|sk_live_[A-Za-z0-9]+|lsv2_[A-Za-z0-9_]+|"
    r"ghp_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+|xox[baprs]-[A-Za-z0-9\-]+|"
    r"AKIA[0-9A-Z]{16}|Bearer\s+[A-Za-z0-9\-._~+/]+=*)"
)
_KV_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|authorization|"
    r"account[_-]?id|acct|user[_-]?id|uid)\b\s*[:=]\s*\S+"
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_LONG_DIGITS = re.compile(r"(?<!\d)\d{12,}(?!\d)")
_USER_ACCOUNT = re.compile(r"(?i)\buser-[A-Za-z0-9_\-]{4,}\b")

_SUMMARY_KEYS = (
    "trace_id",
    "success",
    "elapsed_ms",
    "tokens",
    "skill",
    "tool_blocked_by_permission",
    "tool_blocked_by_sandbox",
    "retrieval_passed_to_generation",
    "memory_kept",
    "memory_dropped",
    "context_compressed",
    "injection_check_ran",
    "hallucination_check_ran",
    "human_step_required",
    "steps",
)


@dataclass
class _Settings:
    directory: Path
    langsmith_enabled: bool


_settings = _Settings(
    directory=Path(os.path.expanduser("~/.lingji/traces")),
    langsmith_enabled=False,
)


def configure(config: Any) -> None:
    """Apply the observability block. LangSmith stays off unless the flag is set."""
    configure_settings(
        getattr(config, "decision_trace_dir", "~/.lingji/traces"),
        bool(getattr(config, "langsmith_enabled", False)),
    )


def configure_settings(directory: str, langsmith_enabled: bool) -> None:
    global _settings
    _settings = _Settings(
        directory=Path(os.path.expanduser(directory or "~/.lingji/traces")),
        langsmith_enabled=bool(langsmith_enabled),
    )


def current_trace() -> DecisionTrace | None:
    return _CURRENT.get()


def _directory() -> Path:
    return _settings.directory


def _trace_path(trace_id: str) -> Path:
    safe = _as_uuid(trace_id)
    return _directory() / f"{safe}.json"


def _as_uuid(value: str | None) -> str:
    if value:
        try:
            return str(uuid.UUID(str(value)))
        except (ValueError, AttributeError, TypeError):
            pass
    return str(uuid.uuid4())


def _env_secrets() -> list[str]:
    found: list[str] = []
    for name in (
        "LANGSMITH_API_KEY",
        "LINGJI_AUTH_TOKEN",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
    ):
        raw = os.environ.get(name, "")
        if raw and len(raw) >= 6:
            found.append(raw)
    return found


def _redact_text(value: str) -> str:
    text = value
    for secret in _env_secrets():
        if secret in text:
            text = text.replace(secret, "[redacted]")
    text = _SECRET.sub("[redacted]", text)
    text = _KV_SECRET.sub(r"\1=[redacted]", text)
    text = _EMAIL.sub("[redacted]", text)
    text = _PHONE.sub("[redacted]", text)
    text = _USER_ACCOUNT.sub("[redacted]", text)
    text = _LONG_DIGITS.sub("[redacted]", text)
    return text


def _safe_label(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = _redact_text(str(value)).strip()
    if not cleaned or "[redacted]" in cleaned:
        return None
    if not _SAFE_LABEL.match(cleaned):
        return None
    if cleaned.lower().startswith("user-"):
        return None
    return cleaned


def _public_step(step: dict[str, Any]) -> dict[str, Any]:
    kind = step.get("step")
    if kind == "skill":
        label = _safe_label(str(step.get("skill") or ""))
        if not label:
            return {}
        return {"step": "skill", "skill": label}
    if kind == "tokens":
        return {"step": "tokens", "tokens": int(step.get("tokens") or 0)}
    if kind == "tool_blocked":
        by = step.get("by")
        if by not in ("permission", "sandbox"):
            return {}
        out: dict[str, Any] = {"step": "tool_blocked", "by": by}
        tool = _safe_label(str(step.get("tool") or ""))
        if tool:
            out["tool"] = tool
        return out
    if kind == "retrieval":
        docs = []
        for item in step.get("documents") or []:
            label = _safe_label(str(item))
            if label and label not in docs:
                docs.append(label)
        return {
            "step": "retrieval",
            "passed_to_generation": bool(step.get("passed_to_generation")),
            "documents": docs,
        }
    if kind == "memory":
        disposition = step.get("disposition")
        if disposition not in ("kept", "dropped"):
            return {}
        return {"step": "memory", "disposition": disposition}
    if kind == "context_compressed":
        return {
            "step": "context_compressed",
            "compressed": bool(step.get("compressed")),
        }
    if kind == "injection_check":
        out = {"step": "injection_check", "ran": True}
        rule_id = _safe_label(str(step.get("rule_id") or ""))
        if rule_id:
            out["rule_id"] = rule_id
        return out
    if kind == "hallucination_check":
        return {
            "step": "hallucination_check",
            "ran": True,
            "unsupported_citation": bool(step.get("unsupported_citation")),
        }
    if kind == "human_step":
        return {"step": "human_step", "required": True}
    if kind == "finish":
        return {
            "step": "finish",
            "success": bool(step.get("success")),
            "elapsed_ms": round(float(step.get("elapsed_ms") or 0), 3),
            "tokens": int(step.get("tokens") or 0),
        }
    return {}


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


class DecisionTrace:
    """Recorded facts for a single decision. Replay reads the stored steps.

    ``elapsed_ms`` is time spent in the call. Time parked on a human step is
    not added.
    """

    def __init__(self, trace_id: str):
        self.trace_id = _as_uuid(trace_id)
        self.success: bool | None = None
        self.elapsed_ms = 0.0
        self.tokens = 0
        self.skills: list[str] = []
        self.tool_blocked_by_permission = False
        self.tool_blocked_by_sandbox = False
        self.retrieval_passed_to_generation = False
        self.retrieval_documents: list[str] = []
        self.memory_kept = False
        self.memory_dropped = False
        self.context_compressed = False
        self.injection_check_ran = False
        self.hallucination_check_ran = False
        self.hallucination_unsupported_citation = False
        self.human_step_required = False
        self.steps: list[dict[str, Any]] = []
        self.started_at = datetime.now(timezone.utc)
        self.ended_at: datetime | None = None
        self._active_started: float | None = time.monotonic()
        self._finished = False
        self._persisted = False
        self._langsmith_sent = False

    @classmethod
    def begin(cls, run_id: str | None = None) -> DecisionTrace:
        return cls(_as_uuid(run_id))

    @classmethod
    def attach(cls, trace_id: str) -> DecisionTrace | None:
        """Re-open an unfinished local trace. A finished trace is left as-is."""
        if not trace_id:
            return None
        path = _trace_path(trace_id)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict) or data.get("success") is not None:
            return None
        trace = cls._from_public(data)
        trace.started_at = datetime.now(timezone.utc) - timedelta(
            milliseconds=trace.elapsed_ms
        )
        trace._active_started = time.monotonic()
        trace._persisted = True
        return trace

    @classmethod
    def _from_public(cls, data: dict[str, Any]) -> DecisionTrace:
        trace = cls(str(data.get("trace_id") or ""))
        trace.success = None
        trace.elapsed_ms = float(data.get("elapsed_ms") or 0)
        trace.tokens = int(data.get("tokens") or 0)
        skill = data.get("skill")
        if isinstance(skill, str) and skill.strip():
            for part in skill.split(","):
                label = _safe_label(part.strip())
                if label and label not in trace.skills:
                    trace.skills.append(label)
        trace.tool_blocked_by_permission = bool(data.get("tool_blocked_by_permission"))
        trace.tool_blocked_by_sandbox = bool(data.get("tool_blocked_by_sandbox"))
        trace.retrieval_passed_to_generation = bool(
            data.get("retrieval_passed_to_generation")
        )
        trace.memory_kept = bool(data.get("memory_kept"))
        trace.memory_dropped = bool(data.get("memory_dropped"))
        trace.context_compressed = bool(data.get("context_compressed"))
        trace.injection_check_ran = bool(data.get("injection_check_ran"))
        trace.hallucination_check_ran = bool(data.get("hallucination_check_ran"))
        trace.human_step_required = bool(data.get("human_step_required"))
        steps = data.get("steps") if isinstance(data.get("steps"), list) else []
        trace.steps = [step for step in (_public_step(s) for s in steps if isinstance(s, dict)) if step]
        for step in trace.steps:
            if step.get("step") == "retrieval":
                for doc in step.get("documents") or []:
                    if doc not in trace.retrieval_documents:
                        trace.retrieval_documents.append(doc)
            if step.get("step") == "hallucination_check":
                trace.hallucination_unsupported_citation = bool(
                    step.get("unsupported_citation")
                )
        trace._active_started = None
        trace._finished = False
        return trace

    def _accrue(self, *, stop: bool) -> None:
        if self._active_started is None:
            return
        self.elapsed_ms += (time.monotonic() - self._active_started) * 1000
        self._active_started = None if stop else time.monotonic()

    def _live_elapsed_ms(self) -> float:
        elapsed = self.elapsed_ms
        if self._active_started is not None:
            elapsed += (time.monotonic() - self._active_started) * 1000
        return round(elapsed, 3)

    def note_skill(self, name: str) -> None:
        label = _safe_label(name)
        if not label or label in self.skills:
            return
        self.skills.append(label)
        self.steps.append({"step": "skill", "skill": label})
        self._touch_if_saved()

    def note_tokens(self, count: int) -> None:
        amount = int(count or 0)
        if amount <= 0:
            return
        self.tokens += amount
        self.steps.append({"step": "tokens", "tokens": amount})
        self._touch_if_saved()

    def note_tool_blocked(
        self,
        *,
        permission: bool = False,
        sandbox: bool = False,
        tool: str = "",
    ) -> None:
        label = _safe_label(tool) or ""
        if permission:
            self.tool_blocked_by_permission = True
            self.steps.append({
                "step": "tool_blocked",
                "by": "permission",
                "tool": label,
            })
        if sandbox:
            self.tool_blocked_by_sandbox = True
            self.steps.append({
                "step": "tool_blocked",
                "by": "sandbox",
                "tool": label,
            })
        if permission or sandbox:
            self._touch_if_saved()

    def note_retrieval_documents(self, document_ids: list[str]) -> None:
        added: list[str] = []
        for raw in document_ids:
            label = _safe_label(raw)
            if label and label not in self.retrieval_documents:
                self.retrieval_documents.append(label)
                added.append(label)
        if not added:
            return
        self.steps.append({
            "step": "retrieval",
            "passed_to_generation": False,
            "documents": list(self.retrieval_documents),
        })
        self._touch_if_saved()

    def note_retrieval_passed(self) -> None:
        if self.retrieval_passed_to_generation:
            return
        self.retrieval_passed_to_generation = True
        self.steps.append({
            "step": "retrieval",
            "passed_to_generation": True,
            "documents": list(self.retrieval_documents),
        })
        self._touch_if_saved()

    def note_memory(self, disposition: str) -> None:
        if disposition == "kept":
            self.memory_kept = True
        elif disposition == "dropped":
            self.memory_dropped = True
        else:
            return
        self.steps.append({"step": "memory", "disposition": disposition})
        self._touch_if_saved()

    def note_context_compressed(self) -> None:
        if self.context_compressed:
            return
        self.context_compressed = True
        self.steps.append({"step": "context_compressed", "compressed": True})
        self._touch_if_saved()

    def note_injection_check(self, rule_id: str = "") -> None:
        safe_rule = _safe_label(rule_id) if rule_id else None
        if not self.injection_check_ran:
            self.injection_check_ran = True
            step: dict[str, Any] = {"step": "injection_check", "ran": True}
            if safe_rule:
                step["rule_id"] = safe_rule
            self.steps.append(step)
            self._touch_if_saved()
            return
        if not safe_rule:
            return
        for step in self.steps:
            if step.get("step") == "injection_check":
                step["rule_id"] = safe_rule
                break
        self._touch_if_saved()

    def note_hallucination_check(self, *, unsupported_citation: bool = False) -> None:
        self.hallucination_unsupported_citation = (
            self.hallucination_unsupported_citation or unsupported_citation
        )
        if not self.hallucination_check_ran:
            self.hallucination_check_ran = True
            self.steps.append({
                "step": "hallucination_check",
                "ran": True,
                "unsupported_citation": self.hallucination_unsupported_citation,
            })
        else:
            for step in self.steps:
                if step.get("step") == "hallucination_check":
                    step["unsupported_citation"] = self.hallucination_unsupported_citation
        self._touch_if_saved()

    def note_human_step(self) -> None:
        if self.human_step_required:
            return
        self.human_step_required = True
        self.steps.append({"step": "human_step", "required": True})
        self._touch_if_saved()

    def checkpoint(self) -> None:
        """Persist the unfinished trace (for example while a person is asked)."""
        if self._finished:
            if not self._persisted:
                self._write()
            return
        self._accrue(stop=True)
        self._write()
        logger.info(
            "decision_trace id=%s path=%s waiting_human=%s",
            self.trace_id,
            _trace_path(self.trace_id),
            self.human_step_required,
        )

    def finish(self, *, success: bool) -> None:
        if self._finished:
            return
        self._accrue(stop=True)
        self.success = bool(success)
        self._finished = True
        self.ended_at = datetime.now(timezone.utc)
        self.steps.append({
            "step": "finish",
            "success": self.success,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "tokens": self.tokens,
        })
        self._write()
        logger.info(
            "decision_trace id=%s path=%s langsmith=%s",
            self.trace_id,
            _trace_path(self.trace_id),
            "sent" if self._langsmith_sent else "local",
        )

    def _skill_label(self) -> str | None:
        if not self.skills:
            return None
        if len(self.skills) == 1:
            return self.skills[0]
        return ", ".join(self.skills)

    def public_view(self) -> dict[str, Any]:
        steps = [step for step in (_public_step(s) for s in self.steps) if step]
        view = {
            "trace_id": self.trace_id,
            "success": self.success,
            "elapsed_ms": self._live_elapsed_ms(),
            "tokens": self.tokens,
            "skill": self._skill_label(),
            "tool_blocked_by_permission": self.tool_blocked_by_permission,
            "tool_blocked_by_sandbox": self.tool_blocked_by_sandbox,
            "retrieval_passed_to_generation": self.retrieval_passed_to_generation,
            "memory_kept": self.memory_kept,
            "memory_dropped": self.memory_dropped,
            "context_compressed": self.context_compressed,
            "injection_check_ran": self.injection_check_ran,
            "hallucination_check_ran": self.hallucination_check_ran,
            "human_step_required": self.human_step_required,
            "steps": steps,
        }
        return {key: view[key] for key in _SUMMARY_KEYS}

    def _touch_if_saved(self) -> None:
        if self._persisted or self._finished:
            self._write()

    def _write(self) -> None:
        view = self.public_view()
        try:
            _atomic_write(_trace_path(self.trace_id), view)
            _atomic_write(_directory() / "latest.json", view)
        except OSError as exc:
            logger.warning("decision_trace local write failed: %s", exc)
            return
        self._persisted = True
        if self._finished:
            self._maybe_langsmith(view)

    def _maybe_langsmith(self, view: dict[str, Any]) -> None:
        if not _settings.langsmith_enabled:
            return
        key = (os.environ.get("LANGSMITH_API_KEY") or "").strip()
        if not key:
            logger.info(
                "decision_trace langsmith skipped (no LANGSMITH_API_KEY) id=%s",
                self.trace_id,
            )
            return
        try:
            import httpx
        except Exception as exc:
            logger.warning("decision_trace langsmith client unavailable: %s", exc)
            return
        endpoint = (
            os.environ.get("LANGSMITH_ENDPOINT") or "https://api.smith.langchain.com"
        ).rstrip("/")
        body = {
            "id": self.trace_id,
            "name": "lingji.decision",
            "run_type": "chain",
            "inputs": {},
            "outputs": view,
            "start_time": self.started_at.isoformat(),
            "end_time": (self.ended_at or datetime.now(timezone.utc)).isoformat(),
            "session_name": "lingji",
            "tags": ["lingji", "decision"],
            "extra": {"metadata": {"source": "lingji-decision-trace"}},
        }
        headers = {"x-api-key": key, "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=3.0) as client:
                if self._langsmith_sent:
                    response = client.patch(
                        f"{endpoint}/runs/{self.trace_id}",
                        json={"outputs": view, "end_time": body["end_time"]},
                        headers=headers,
                    )
                else:
                    response = client.post(
                        f"{endpoint}/runs",
                        json=body,
                        headers=headers,
                    )
                    if response.status_code == 409:
                        response = client.patch(
                            f"{endpoint}/runs/{self.trace_id}",
                            json={"outputs": view, "end_time": body["end_time"]},
                            headers=headers,
                        )
            if response.status_code >= 400:
                logger.warning(
                    "decision_trace langsmith status=%s id=%s",
                    response.status_code,
                    self.trace_id,
                )
                return
            self._langsmith_sent = True
        except Exception as exc:
            logger.warning("decision_trace langsmith failed: %s", exc)


def note_skill(name: str) -> None:
    trace = current_trace()
    if trace is not None:
        trace.note_skill(name)


def note_tokens(count: int) -> None:
    trace = current_trace()
    if trace is not None:
        trace.note_tokens(count)


def note_tool_blocked(
    *,
    permission: bool = False,
    sandbox: bool = False,
    tool: str = "",
) -> None:
    trace = current_trace()
    if trace is not None:
        trace.note_tool_blocked(permission=permission, sandbox=sandbox, tool=tool)


def note_retrieval_documents(document_ids: list[str]) -> None:
    trace = current_trace()
    if trace is not None:
        trace.note_retrieval_documents(document_ids)


def note_retrieval_passed() -> None:
    trace = current_trace()
    if trace is not None:
        trace.note_retrieval_passed()


def note_memory(disposition: str) -> None:
    trace = current_trace()
    if trace is not None:
        trace.note_memory(disposition)


def note_context_compressed() -> None:
    trace = current_trace()
    if trace is not None:
        trace.note_context_compressed()


def note_injection_check(rule_id: str = "") -> None:
    trace = current_trace()
    if trace is not None:
        trace.note_injection_check(rule_id)


def note_hallucination_check(*, unsupported_citation: bool = False) -> None:
    trace = current_trace()
    if trace is not None:
        trace.note_hallucination_check(unsupported_citation=unsupported_citation)


def note_human_step() -> None:
    trace = current_trace()
    if trace is not None:
        trace.note_human_step()


@contextmanager
def bound_trace(trace: DecisionTrace) -> Iterator[DecisionTrace]:
    token = _CURRENT.set(trace)
    try:
        yield trace
    except Exception:
        if not trace._finished:
            trace.finish(success=False)
        raise
    finally:
        if not trace._persisted:
            trace.checkpoint()
        _CURRENT.reset(token)


@contextmanager
def decision_run(run_id: str | None = None) -> Iterator[DecisionTrace]:
    """Open the trace for one run. The caller finishes it with success or failure."""
    trace = DecisionTrace.begin(run_id)
    with bound_trace(trace) as opened:
        yield opened


def load_trace(trace_id: str | None = None) -> dict[str, Any]:
    if trace_id:
        path = _trace_path(trace_id)
    else:
        path = _directory() / "latest.json"
    if not path.is_file():
        raise FileNotFoundError(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise FileNotFoundError(path)
    return data


def replay(trace_id: str | None = None) -> dict[str, Any]:
    """Load one stored trace and return its steps in recorded order.

    This does not call a model or re-run tools.
    """
    record = load_trace(trace_id)
    steps = record.get("steps") if isinstance(record.get("steps"), list) else []
    record["steps"] = [step for step in steps if isinstance(step, dict)]
    return record


def main(argv: list[str] | None = None) -> int:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    trace_id = args[0] if args else None
    try:
        record = replay(trace_id)
    except FileNotFoundError:
        print("no decision trace", file=sys.stderr)
        return 1
    json.dump(record, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
