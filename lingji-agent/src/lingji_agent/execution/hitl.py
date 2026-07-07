"""HITL (Human-in-the-Loop) 挂起/恢复 — SQLite 审计 + LangGraph interrupt 配合"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)


class HITLDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


@dataclass
class HITLRequest:
    task_id: str
    description: str
    risk_level: str
    checkpoint_id: str
    thread_id: str = ""
    future: asyncio.Future = field(default_factory=asyncio.Future)


@dataclass(frozen=True)
class RecoveredHITLContext:
    """Agent 重启后从 SQLite 重建的 HITL 续跑上下文（GAP-002）。"""

    session_id: str
    task_id: str
    thread_id: str
    device_id: str
    user_text: str
    system_prompt: str
    description: str
    risk_level: str
    checkpoint_status: str


class PendingRunLike(Protocol):
    thread_id: str
    device_id: str
    user_text: str
    system_prompt: str
    run_started_at: float


def hitl_remaining_seconds(
    created_at: str | None,
    timeout_sec: float,
    *,
    now: datetime | None = None,
) -> float:
    """Return seconds until HITL auto-timeout; <=0 means already expired."""
    if timeout_sec <= 0:
        return 0.0
    if not created_at:
        return float(timeout_sec)
    # SQLite CURRENT_TIMESTAMP is UTC; compare in UTC to avoid local skew.
    now = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    raw = str(created_at).strip()
    created: datetime | None = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            created = datetime.strptime(raw[:26], fmt)
            break
        except ValueError:
            continue
    if created is None:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            created = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            return float(timeout_sec)
    return float(timeout_sec) - (now - created).total_seconds()


def build_recovered_context(
    session_row: dict[str, Any],
    *,
    default_device_id: str = "",
) -> RecoveredHITLContext:
    """从 hitl_sessions + checkpoints 联表行解析续跑所需字段。"""
    state = json.loads(session_row.get("agent_state_json") or "{}")
    messages = state.get("messages") or []

    user_text = ""
    system_prompt = ""
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content") or ""
        if role == "system":
            system_prompt = content
        elif role == "user":
            user_text = content

    thread_id = session_row.get("thread_id") or ""
    if ":" in thread_id:
        device_id = thread_id.split(":", 1)[0]
    else:
        device_id = default_device_id

    return RecoveredHITLContext(
        session_id=session_row["id"],
        task_id=session_row["task_id"],
        thread_id=thread_id,
        device_id=device_id or default_device_id,
        user_text=user_text,
        system_prompt=system_prompt,
        description=session_row.get("description") or "",
        risk_level=session_row.get("risk_level") or "critical",
        checkpoint_status=session_row.get("checkpoint_status") or "",
    )


def register_recovered_pending_run(
    pending_runs: dict[str, PendingRunLike],
    session_row: dict[str, Any],
    pending_run_factory: Callable[..., PendingRunLike],
    *,
    default_device_id: str = "",
    run_started_at: float | None = None,
) -> PendingRunLike:
    """将 DB 中的未决 HITL 注册到内存 pending_runs，供 Command(resume) 使用。"""
    ctx = build_recovered_context(session_row, default_device_id=default_device_id)
    pending = pending_run_factory(
        thread_id=ctx.thread_id,
        device_id=ctx.device_id,
        user_text=ctx.user_text,
        system_prompt=ctx.system_prompt,
        run_started_at=run_started_at if run_started_at is not None else time.monotonic(),
    )
    pending_runs[ctx.task_id] = pending
    logger.info(
        "GAP-002 恢复 pending run: task=%s thread=%s resumable=1",
        ctx.task_id,
        ctx.thread_id,
    )
    return pending


def find_pending_hitl_for_thread(
    conn,
    thread_id: str,
    pending_runs: dict[str, PendingRunLike] | None = None,
) -> dict[str, str] | None:
    """返回指定 thread 上未决 HITL 的 Web UI payload，无则 None。"""
    if not thread_id:
        return None
    pending_runs = pending_runs or {}
    from lingji_agent.foundation.db import (
        get_pending_hitl_session_by_task_id,
        get_pending_hitl_sessions_with_checkpoints,
    )

    for task_id, pending in pending_runs.items():
        if pending.thread_id == thread_id:
            session = get_pending_hitl_session_by_task_id(conn, task_id)
            return {
                "task_id": task_id,
                "description": (session or {}).get("description") or "危险操作需审批",
                "risk_level": (session or {}).get("risk_level") or "critical",
                "tool": (session or {}).get("tool") or "",
            }

    for session in get_pending_hitl_sessions_with_checkpoints(conn):
        if session.get("thread_id") == thread_id:
            return {
                "task_id": session["task_id"],
                "description": session.get("description") or "",
                "risk_level": session.get("risk_level") or "critical",
            }
    return None


def thread_has_pending_hitl(
    conn,
    thread_id: str,
    pending_runs: dict[str, PendingRunLike] | None = None,
) -> bool:
    """当前 thread 是否仍有未决 HITL。"""
    return find_pending_hitl_for_thread(conn, thread_id, pending_runs) is not None


class HITLManager:
    """HITL 审批：LangGraph interrupt 模式下负责 SQLite 审计；legacy 模式仍支持 Future 阻塞"""

    def __init__(self, db_conn=None, default_timeout: float = 300.0):
        self._db = db_conn
        self._requests: dict[str, HITLRequest] = {}
        self._default_timeout = default_timeout

    def set_db(self, conn):
        self._db = conn

    def record_interrupt(
        self,
        task_id: str,
        description: str,
        risk_level: str,
        thread_id: str,
        agent_state: dict[str, Any] | None = None,
    ) -> str:
        """interrupt 挂起时写入 checkpoints + hitl_sessions（供崩溃恢复与审计）"""
        checkpoint_id = str(uuid.uuid4())
        if self._db:
            from lingji_agent.foundation.db import save_checkpoint

            if agent_state:
                save_checkpoint(
                    self._db,
                    checkpoint_id,
                    thread_id=thread_id,
                    agent_state=agent_state,
                    status="waiting_hitl",
                )
            self._db.execute(
                """INSERT INTO hitl_sessions (id, checkpoint_id, task_id, description, risk_level)
                   VALUES (?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), checkpoint_id, task_id, description, risk_level),
            )
            self._db.commit()
        logger.info(
            "HITL interrupt 记录: task=%s thread=%s desc=%s",
            task_id,
            thread_id,
            description[:100],
        )
        return checkpoint_id

    def resolve_interrupt(self, task_id: str, decision: str) -> None:
        """审批完成后更新 hitl_sessions 状态"""
        if not self._db:
            return
        from lingji_agent.foundation.db import update_hitl_session

        row = self._db.execute(
            """SELECT id FROM hitl_sessions
               WHERE task_id = ? AND status = 'pending'
               ORDER BY created_at DESC LIMIT 1""",
            (task_id,),
        ).fetchone()
        if row:
            update_hitl_session(self._db, row[0], decision)

    async def request_approval(
        self,
        task_id: str,
        description: str,
        risk_level: str,
        agent_state: dict[str, Any] | None = None,
        thread_id: str = "",
    ) -> HITLDecision:
        """Legacy：asyncio.Future 阻塞等待（无 checkpointer 的测试/降级路径）"""
        checkpoint_id = str(uuid.uuid4())
        request = HITLRequest(
            task_id=task_id,
            description=description,
            risk_level=risk_level,
            checkpoint_id=checkpoint_id,
            thread_id=thread_id,
        )

        if self._db and agent_state:
            from lingji_agent.foundation.db import save_checkpoint

            save_checkpoint(
                self._db,
                checkpoint_id,
                thread_id=thread_id or task_id,
                agent_state=agent_state,
                status="waiting_hitl",
            )
            self._db.execute(
                """INSERT INTO hitl_sessions (id, checkpoint_id, task_id, description, risk_level)
                   VALUES (?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), checkpoint_id, task_id, description, risk_level),
            )
            self._db.commit()

        self._requests[task_id] = request
        logger.info("HITL 挂起(legacy): task=%s risk=%s", task_id, risk_level)

        try:
            decision = await asyncio.wait_for(request.future, timeout=self._default_timeout)
            return decision
        except asyncio.TimeoutError:
            logger.warning("HITL 审批超时: task=%s", task_id)
            self._resolve(task_id, HITLDecision.TIMEOUT)
            return HITLDecision.TIMEOUT

    def approve(self, task_id: str):
        self._resolve(task_id, HITLDecision.APPROVED)

    def reject(self, task_id: str):
        self._resolve(task_id, HITLDecision.REJECTED)

    def _resolve(self, task_id: str, decision: HITLDecision):
        request = self._requests.get(task_id)
        if request is None:
            return
        if request.future.done():
            return

        request.future.set_result(decision)
        self.resolve_interrupt(task_id, decision.value)
        del self._requests[task_id]

    def get_pending_count(self) -> int:
        return len(self._requests)

    async def recover_pending_sessions(self, on_resend=None):
        if not self._db:
            return 0
        from lingji_agent.foundation.db import get_pending_hitl_sessions_with_checkpoints

        pending = get_pending_hitl_sessions_with_checkpoints(self._db)
        for session in pending:
            logger.warning(
                "恢复未决 HITL: %s thread=%s (desc=%s)",
                session["task_id"],
                session.get("thread_id", "?"),
                session["description"],
            )
            if on_resend:
                await on_resend(session)
        return len(pending)
