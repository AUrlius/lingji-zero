"""灵机计划 Agent 主入口

启动序列：PID 锁 → 配置 → DB → LLM → Graph → Gateway（记忆层后台预热）
"""

import argparse
import asyncio
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import structlog.contextvars

from lingji_agent.foundation.config import load_config
from lingji_agent.foundation.logger import setup_logging, get_logger
from lingji_agent.foundation.db import init_db
from lingji_agent.foundation.checkpointer import open_checkpointer
from lingji_agent.foundation import run_metrics
from lingji_agent.foundation.pid_lock import (
    acquire_pid_lock,
    release_pid_lock,
    agent_status,
    stop_running_agent,
)
from lingji_agent.cognitive.llm_provider import create_connector
from lingji_agent.cognitive.orchestrator import (
    build_graph,
    run_agent,
    build_run_config,
    has_interrupt,
    extract_interrupt_payloads,
)
from lingji_agent.cognitive.session_history import load_thread_ui_history
from lingji_agent.cognitive.prompt_manager import PromptManager
from lingji_agent.execution.registry import registry
from lingji_agent.execution.tools import fs_tools, sys_tools, file_tools  # noqa: 触发 @registry.register
from lingji_agent.execution.hitl import (
    HITLManager,
    build_recovered_context,
    find_pending_hitl_for_thread,
    hitl_remaining_seconds,
    register_recovered_pending_run,
    thread_has_pending_hitl,
)
from lingji_agent.foundation.db import (
    get_pending_hitl_session_by_task_id,
    get_pending_hitl_sessions_with_checkpoints,
    get_active_chat_thread,
    list_chat_sessions,
    upsert_chat_session,
    set_active_chat_session,
    update_hitl_session,
    _session_title,
)
from lingji_agent.network.incoming_files import (
    save_uploads_to_pc,
    text_implies_file_organization,
    uploads_all_saved,
    format_saved_reply,
    format_upload_errors,
    validate_incoming_dir_config,
)
from lingji_agent.execution.sandbox import create_sandbox
from lingji_agent.memory import create_memory_manager
from lingji_agent.observability import init_observability, shutdown_observability
from lingji_agent.observability.tracing import add_span_event, trace_span
from lingji_agent.network.ws_client import GatewayClient
from lingji_agent.network.router import Router
from lingji_agent.network.protocol import Message, MsgType, build_agent_res_payload
from langgraph.types import Command

logger = get_logger(__name__)


@dataclass
class PendingRun:
    thread_id: str
    device_id: str  # Web connection id (conn-*)
    user_text: str
    system_prompt: str
    user_id: str = ""  # Fleet user id (user-*); fan-out to all Web entries
    run_started_at: float = field(default_factory=time.monotonic)


def _resolve_web_client(msg: Message) -> tuple[str, str]:
    """Return (connection_id, user_id). Sessions use user_id; WS route uses connection_id."""
    conn_id = msg.device_id
    raw = msg.payload.get("user_id")
    if isinstance(raw, str) and raw.strip():
        return conn_id, raw.strip()
    return conn_id, conn_id


def _pending_user_id(pending: PendingRun) -> str:
    if pending.user_id:
        return pending.user_id
    if ":" in pending.thread_id:
        return pending.thread_id.split(":", 1)[0]
    return pending.device_id


def _format_tool_results(tool_results: list[dict]) -> str:
    if not tool_results:
        return ""
    parts = []
    for item in tool_results:
        name = item.get("tool_name", "unknown")
        result = item.get("result", "")
        parts.append(f"{name}: {result}")
    return "\n".join(parts)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="灵机 Agent Client")
    parser.add_argument(
        "config_path",
        nargs="?",
        default=None,
        help="配置文件路径（可选）",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="停止已在运行的 Agent 并清理 PID 锁",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="查看 Agent 是否在运行",
    )
    return parser.parse_args(argv)


async def main(config_path: str | None = None):
    if not acquire_pid_lock():
        sys.exit(1)

    config = load_config(config_path)
    os.environ.setdefault("LINGJI_GATEWAY_HOST", config.network.gateway_host)
    os.environ.setdefault("LINGJI_GATEWAY_PORT", str(config.network.gateway_port))
    if config.network.auth_token:
        os.environ.setdefault("LINGJI_AUTH_TOKEN", config.network.auth_token)
    setup_logging(
        trace_log=config.observability.trace_log_enabled and config.observability.enabled,
    )
    init_observability(config.observability)
    logger.info("灵机计划 Agent 启动中...")
    logger.info("Gateway: %s:%s", config.network.gateway_host, config.network.gateway_port)
    logger.info("Device: %s", config.network.device_id)
    try:
        incoming_resolved = validate_incoming_dir_config(config.network.incoming_dir)
    except ValueError as e:
        logger.error("%s", e)
        sys.exit(1)
    logger.info("incoming_dir: %s", incoming_resolved)

    sandbox = create_sandbox()
    logger.info("沙箱: %s (docker_available=%s)", type(sandbox).__name__, sandbox.is_available())

    db = init_db()
    logger.info("数据库已就绪")

    hitl_timeout_sec = float(config.security.hitl_timeout_sec)
    hitl_mgr = HITLManager(db_conn=db, default_timeout=hitl_timeout_sec)
    logger.info("HITL 管理器已就绪 (timeout=%ds)", int(hitl_timeout_sec))

    connector = create_connector(config)
    logger.info("LLM: %s (%s)", connector.model_name, type(connector).__name__)

    prompt_manager = PromptManager(
        device_id=config.network.device_id,
        registry=registry,
    )

    memory_mgr = create_memory_manager(config.memory, llm_connector=connector)
    memory_warmup: asyncio.Task | None = None
    if config.memory.enabled:
        logger.info("记忆层已启用 (后台预热，不阻塞 Gateway 连接)")
        memory_warmup = asyncio.create_task(memory_mgr.warmup())
    else:
        logger.info("记忆层已关闭")

    async with open_checkpointer() as checkpointer:
        graph = build_graph(
            connector=connector,
            registry=registry,
            hitl_manager=hitl_mgr,
            checkpointer=checkpointer,
        )
        logger.info("LangGraph 已编译 (%d 个工具, checkpointer=on)", len(registry.list_all()))
        run_metrics.log_summary()

        pending_runs: dict[str, PendingRun] = {}
        hitl_watchdogs: dict[str, asyncio.Task] = {}
        hitl_resume_lock = asyncio.Lock()
        device_active_threads: dict[str, str] = {}
        router = Router()

        async def _reply_session_view(
            user_id: str,
            thread_id: str,
            *,
            connection_id: str,
            status: str,
            message: str = "",
        ) -> None:
            """会话列表/切换：回填 history，并附带该 thread 的 pending HITL。"""
            sessions = list_chat_sessions(db, user_id)
            sw = next((s for s in sessions if s["thread_id"] == thread_id), None)
            switch_title = sw["title"] if sw else "会话"
            history = await _thread_ui_history(thread_id)
            pending_hitl = find_pending_hitl_for_thread(db, thread_id, pending_runs)
            extra: dict = {
                "status": status,
                "thread_id": thread_id,
                "sessions": sessions,
                "history": history,
            }
            if pending_hitl:
                extra["pending_hitl"] = pending_hitl
            await _send_agent_reply(
                message or f"已切换到：{switch_title}",
                target_device_id=connection_id,
                target_user_id=user_id,
                **extra,
            )

        def _resolve_thread_id(
            device_id: str,
            new_session: bool,
            switch_thread_id: str | None = None,
        ) -> tuple[str, bool]:
            """返回 (thread_id, continue_thread)。"""
            if switch_thread_id:
                device_active_threads[device_id] = switch_thread_id
                return switch_thread_id, True
            if device_id not in device_active_threads:
                active = get_active_chat_thread(db, device_id)
                if active and not new_session:
                    device_active_threads[device_id] = active
                    return active, True
            if new_session or device_id not in device_active_threads:
                thread_id = f"{device_id}:{uuid.uuid4()}"
                device_active_threads[device_id] = thread_id
                return thread_id, False
            return device_active_threads[device_id], True

        async def _finalize_turn(
            result: dict,
            conversation_thread_id: str,
            user_text: str,
        ) -> str:
            reply_text = result.get("final_response", "（无回复）")
            tool_output = _format_tool_results(result.get("tool_results", []))
            await memory_mgr.save_episodic_memory(
                thread_id=conversation_thread_id,
                role="user",
                content=user_text,
            )
            await memory_mgr.save_episodic_memory(
                thread_id=conversation_thread_id,
                role="assistant",
                content=reply_text,
                tool_output=tool_output or None,
            )
            return reply_text

        def _cancel_hitl_watchdog(task_id: str) -> None:
            task = hitl_watchdogs.pop(task_id, None)
            if task and not task.done():
                task.cancel()

        async def _send_hitl_requests(result: dict, pending: PendingRun) -> None:
            for payload in extract_interrupt_payloads(result):
                task_id = payload.get("task_id", "")
                if not task_id:
                    continue
                pending_runs[task_id] = pending
                run_metrics.increment("hitl_interrupt_total")
                if client.ws and not getattr(client.ws, "closed", False):
                    hitl_msg = Message(
                        msg_type=MsgType.HITL_REQ,
                        device_id=config.network.device_id,
                        payload={
                            "task_id": task_id,
                            "description": payload.get("description", ""),
                            "risk_level": "critical",
                            "tool": payload.get("tool", ""),
                            "target_device_id": pending.device_id,
                            "target_user_id": pending.user_id or pending.device_id,
                        },
                    )
                    await client.send(hitl_msg)
                    logger.info("已发送 HITL_REQ: task=%s", task_id)
                _cancel_hitl_watchdog(task_id)
                _schedule_hitl_watchdog(task_id)

        async def _send_agent_reply(
            reply_text: str,
            attachments: list[dict] | None = None,
            *,
            target_device_id: str = "",
            target_user_id: str = "",
            **extra_payload,
        ) -> None:
            logger.info(
                "🤖 回复 (%d chars, %d attachments) → conn=%s user=%s: %s",
                len(reply_text),
                len(attachments or []),
                target_device_id or "?",
                target_user_id or "?",
                reply_text[:200],
            )
            if target_user_id:
                extra_payload["target_user_id"] = target_user_id
            if client.ws and not getattr(client.ws, "closed", False):
                reply_msg = Message(
                    msg_type=MsgType.AGENT_RES,
                    device_id=config.network.device_id,
                    payload=build_agent_res_payload(
                        reply_text,
                        attachments,
                        target_device_id=target_device_id or None,
                        **extra_payload,
                    ),
                )
                await client.send(reply_msg)

        def _log_run_complete(pending: PendingRun | None, *, hitl_pending: int = 0) -> None:
            if pending is None:
                return
            duration_ms = (time.monotonic() - pending.run_started_at) * 1000
            run_metrics.increment("run_complete_total")
            run_metrics.record_run_duration(duration_ms / 1000.0)
            logger.info(
                "run_complete duration_ms=%.1f hitl_pending=%d device_id=%s",
                duration_ms,
                hitl_pending,
                pending.device_id,
            )

        async def _thread_ui_history(thread_id: str) -> list[dict]:
            """从 LangGraph checkpoint 提取 Web UI 可渲染历史。"""
            if not thread_id:
                return []
            return await load_thread_ui_history(
                graph,
                thread_id,
                connector=connector,
                registry=registry,
                hitl_manager=hitl_mgr,
                sanitizer_force_docker=config.security.sanitizer_force_docker,
            )

        async def _graph_has_interrupt(thread_id: str) -> bool:
            """LangGraph checkpointer 中该 thread 是否仍处于 interrupt 挂起。"""
            run_config = build_run_config(
                thread_id=thread_id,
                connector=connector,
                registry=registry,
                hitl_manager=hitl_mgr,
                sanitizer_force_docker=config.security.sanitizer_force_docker,
            )
            try:
                snap = await graph.aget_state(run_config)
            except Exception as e:
                logger.warning("GAP-002 读取 graph 状态失败 thread=%s: %s", thread_id, e)
                return False
            return bool(snap and snap.interrupts)

        def _register_recovered_session(session: dict) -> PendingRun | None:
            """从 SQLite 恢复 pending_runs 条目（GAP-002）。"""
            try:
                return register_recovered_pending_run(
                    pending_runs,
                    session,
                    PendingRun,
                    default_device_id=config.network.device_id,
                )
            except Exception as e:
                logger.error(
                    "GAP-002 恢复 pending run 失败 task=%s: %s",
                    session.get("task_id"),
                    e,
                )
                return None

        async def _ensure_pending_run(task_id: str) -> PendingRun | None:
            """内存无 pending 时从 DB 懒加载（崩溃后 HITL_RES 直达场景）。"""
            if task_id in pending_runs:
                return pending_runs[task_id]
            session = get_pending_hitl_session_by_task_id(db, task_id)
            if not session:
                return None
            pending = _register_recovered_session(session)
            if pending and await _graph_has_interrupt(pending.thread_id):
                _schedule_hitl_watchdog(task_id, session.get("created_at"))
            return pending

        async def _resume_from_hitl(task_id: str, decision: str) -> bool:
            """恢复挂起的 graph；返回是否已发送 AGENT_RES（False 表示再次 interrupt 挂起）"""
            async with hitl_resume_lock:
                _cancel_hitl_watchdog(task_id)
                pending = await _ensure_pending_run(task_id)
                if pending is None:
                    logger.warning("HITL resume 失败: task=%s 无 pending 上下文", task_id)
                    return False

                if not await _graph_has_interrupt(pending.thread_id):
                    logger.error(
                        "GAP-002: thread=%s 无 LangGraph interrupt，无法 Command(resume)",
                        pending.thread_id,
                    )
                    await _send_agent_reply(
                        "❌ 无法恢复挂起的审批：Agent 状态已丢失，请重新发送指令。",
                        target_device_id=pending.device_id,
                        target_user_id=_pending_user_id(pending),
                    )
                    hitl_mgr.resolve_interrupt(task_id, "error")
                    pending_runs.pop(task_id, None)
                    return True

                hitl_mgr.resolve_interrupt(task_id, decision)
                pending_runs.pop(task_id, None)

                run_config = build_run_config(
                    thread_id=pending.thread_id,
                    connector=connector,
                    registry=registry,
                    hitl_manager=hitl_mgr,
                    sanitizer_force_docker=config.security.sanitizer_force_docker,
                )

                try:
                    result = await graph.ainvoke(Command(resume=decision), run_config)
                    while has_interrupt(result):
                        await _send_hitl_requests(result, pending)
                        logger.info("Agent 再次挂起等待 HITL (thread=%s)", pending.thread_id)
                        return False

                    reply_text = await _finalize_turn(
                        result, pending.thread_id, pending.user_text,
                    )
                    await _send_agent_reply(
                        reply_text,
                        result.get("attachments") or None,
                        target_device_id=pending.device_id,
                        target_user_id=_pending_user_id(pending),
                    )
                    _log_run_complete(pending)
                    return True
                except Exception as e:
                    run_metrics.increment("agent_errors")
                    logger.error("HITL 恢复执行失败: %s", e)
                    await _send_agent_reply(
                        f"❌ HITL 恢复失败：{e}",
                        target_device_id=pending.device_id,
                        target_user_id=_pending_user_id(pending),
                    )
                    _log_run_complete(pending)
                    return True

        async def _hitl_timeout_watch(task_id: str, delay_sec: float | None = None) -> None:
            try:
                await asyncio.sleep(delay_sec if delay_sec is not None else hitl_timeout_sec)
                if task_id not in pending_runs:
                    return
                logger.warning("HITL 审批超时: task=%s", task_id)
                run_metrics.increment("hitl_timeout_total")
                await _resume_from_hitl(task_id, "timeout")
            except asyncio.CancelledError:
                pass

        def _schedule_hitl_watchdog(task_id: str, created_at: str | None = None) -> None:
            remaining = hitl_remaining_seconds(created_at, hitl_timeout_sec)
            if remaining <= 0:
                asyncio.create_task(_resume_from_hitl(task_id, "timeout"))
                return
            _cancel_hitl_watchdog(task_id)
            hitl_watchdogs[task_id] = asyncio.create_task(
                _hitl_timeout_watch(task_id, remaining),
                name=f"hitl-timeout-{task_id}",
            )

        async def on_cmd_text(msg: Message):
            user_text = msg.payload.get("text", "")
            uploads = msg.payload.get("uploads") or []
            conn_id, user_id = _resolve_web_client(msg)
            device_id = user_id
            new_session = bool(msg.payload.get("new_session"))
            switch_thread_id = msg.payload.get("thread_id") or None
            run_id = str(uuid.uuid4())
            run_started_at = time.monotonic()
            structlog.contextvars.bind_contextvars(run_id=run_id, device_id=device_id)

            with trace_span(
                "agent.run",
                {"run_id": run_id, "device_id": device_id},
            ):
                run_metrics.increment("cmd_total")
                logger.info("📱 [%s] %s", device_id, user_text[:120] if user_text else "(upload/switch)")

                is_session_switch = (
                    bool(switch_thread_id)
                    and not user_text.strip()
                    and not uploads
                    and not new_session
                )
                if is_session_switch:
                    thread_id, _continue = _resolve_thread_id(
                        device_id, new_session, switch_thread_id,
                    )
                    set_active_chat_session(db, device_id, thread_id)
                    await _reply_session_view(
                        user_id,
                        thread_id,
                        connection_id=conn_id,
                        status="session_switched",
                    )
                    structlog.contextvars.unbind_contextvars("run_id", "device_id")
                    return

                if uploads:
                    upload_block, upload_results = await save_uploads_to_pc(
                        uploads,
                        incoming_dir=config.network.incoming_dir,
                        gateway_host=config.network.gateway_host,
                        gateway_port=config.network.gateway_port,
                        auth_token=config.network.auth_token,
                    )
                    if not uploads_all_saved(upload_results, len(uploads)):
                        await _send_agent_reply(
                            format_upload_errors(upload_results),
                            target_device_id=conn_id,
                            target_user_id=user_id,
                        )
                        structlog.contextvars.unbind_contextvars("run_id", "device_id")
                        return

                    plain_text = user_text.strip()
                    if not text_implies_file_organization(plain_text):
                        run_metrics.increment("upload_fastpath_total")
                        thread_id, _continue = _resolve_thread_id(
                            device_id, new_session, switch_thread_id,
                        )
                        title = plain_text or upload_results[0].get("name", "上传文件")
                        upsert_chat_session(
                            db, device_id, thread_id, _session_title(title), set_active=True,
                        )
                        await _send_agent_reply(
                            format_saved_reply(upload_results),
                            target_device_id=conn_id,
                            target_user_id=user_id,
                        )
                        structlog.contextvars.unbind_contextvars("run_id", "device_id")
                        return

                    user_text = (
                        f"{plain_text}\n\n{upload_block}".strip()
                        if plain_text
                        else upload_block
                    )

                thread_id, continue_thread = _resolve_thread_id(
                    device_id, new_session, switch_thread_id,
                )
                if new_session:
                    logger.info("新对话 session thread=%s device=%s", thread_id, device_id)

                if user_text.strip() or new_session:
                    upsert_chat_session(
                        db,
                        device_id,
                        thread_id,
                        _session_title(user_text) if user_text.strip() else "新对话",
                        set_active=True,
                    )
                elif switch_thread_id:
                    set_active_chat_session(db, device_id, thread_id)

                if not user_text.strip():
                    structlog.contextvars.unbind_contextvars("run_id", "device_id")
                    return

                if thread_has_pending_hitl(db, thread_id, pending_runs):
                    await _send_agent_reply(
                        "⏳ 当前会话仍有危险操作等待审批，请先批准或拒绝后再发送新消息。",
                        target_device_id=conn_id,
                        target_user_id=user_id,
                    )
                    structlog.contextvars.unbind_contextvars("run_id", "device_id")
                    return

                if memory_warmup and not memory_warmup.done():
                    await memory_warmup

                retrieved_context = memory_mgr.retrieve_context(
                    user_text,
                    episodic_thread_id=thread_id,
                )

                if config.security.guardrails_enabled:
                    from lingji_agent.security.guardrails import SecurityGuardrail

                    guardrail = SecurityGuardrail()
                    gr = guardrail.inspect(user_text, context=retrieved_context)
                    if not gr.allowed:
                        logger.warning(
                            "guardrail_blocked rule_id=%s reason=%s",
                            gr.rule_id,
                            gr.reason,
                        )
                        add_span_event(
                            "security.blocked",
                            {"rule_id": gr.rule_id, "reason": gr.reason},
                        )
                        if config.security.guardrails_block:
                            run_metrics.increment(
                                "guardrail_blocked_total",
                                rule_id=gr.rule_id,
                            )
                            await _send_agent_reply(
                                SecurityGuardrail.block_message(gr),
                                target_device_id=conn_id,
                            target_user_id=user_id,
                            )
                            structlog.contextvars.unbind_contextvars("run_id", "device_id")
                            return

                system_prompt = prompt_manager.build_system_prompt(
                    retrieved_memory_context=retrieved_context,
                )
                pending = PendingRun(
                    thread_id=thread_id,
                    device_id=conn_id,
                    user_id=user_id,
                    user_text=user_text,
                    system_prompt=system_prompt,
                    run_started_at=run_started_at,
                )

                attachments: list[dict] | None = None
                try:
                    result = await run_agent(
                        graph=graph,
                        user_message=user_text,
                        system_prompt=system_prompt,
                        connector=connector,
                        registry=registry,
                        thread_id=thread_id,
                        hitl_manager=hitl_mgr,
                        sanitizer_force_docker=config.security.sanitizer_force_docker,
                        continue_thread=continue_thread,
                    )
                    if has_interrupt(result):
                        await _send_hitl_requests(result, pending)
                        logger.info("Agent 挂起等待 HITL 审批 (thread=%s)", thread_id)
                        return

                    reply_text = await _finalize_turn(result, thread_id, user_text)
                    attachments = result.get("attachments") or None
                except Exception as e:
                    run_metrics.increment("agent_errors")
                    logger.error("Agent 执行失败: %s", e)
                    reply_text = f"❌ AI 服务暂不可用，请稍后重试。\n\n错误详情：{e}"

                await _send_agent_reply(
                    reply_text,
                    attachments,
                    target_device_id=conn_id,
                    target_user_id=user_id,
                )
                _log_run_complete(pending)
            structlog.contextvars.unbind_contextvars("run_id", "device_id")

        async def on_cmd_list_sessions(msg: Message):
            conn_id, user_id = _resolve_web_client(msg)
            sessions = list_chat_sessions(db, user_id)
            active_tid = next(
                (s["thread_id"] for s in sessions if s.get("active")),
                None,
            )
            if not active_tid:
                active_tid = get_active_chat_thread(db, user_id)
            if active_tid:
                await _reply_session_view(
                    user_id,
                    active_tid,
                    connection_id=conn_id,
                    status="sessions",
                    message="",
                )
            else:
                await _send_agent_reply(
                    "",
                    target_device_id=conn_id,
                    target_user_id=user_id,
                    status="sessions",
                    sessions=sessions,
                    history=[],
                )

        router.register(MsgType.CMD_TEXT, on_cmd_text)
        router.register(MsgType.CMD_LIST_SESSIONS, on_cmd_list_sessions)

        async def on_hitl_res(msg: Message):
            decision = msg.payload.get("decision", "rejected")
            task_id = msg.payload.get("task_id", "")
            logger.info("HITL 审批: %s -> %s", task_id, decision)
            await _resume_from_hitl(task_id, decision)

        router.register(MsgType.HITL_RES, on_hitl_res)

        client = GatewayClient(config.network, router)

        def on_connected():
            logger.info("已连接到灵机 Gateway")
            tools = [t.name for t in registry.list_all()]
            logger.info("可用工具: %s", ", ".join(tools) if tools else "（无）")
            asyncio.create_task(_recover_pending())

        async def _recover_pending():
            sessions = get_pending_hitl_sessions_with_checkpoints(db)
            recovered = 0
            for session in sessions:
                task_id = session["task_id"]
                thread_id = session.get("thread_id") or ""
                session_id = session["id"]
                created_at = session.get("created_at")

                remaining = hitl_remaining_seconds(created_at, hitl_timeout_sec)
                if remaining <= 0:
                    update_hitl_session(db, session_id, "timeout")
                    logger.warning("HITL 已超时，跳过恢复: task=%s", task_id)
                    continue

                resumable = await _graph_has_interrupt(thread_id)
                if not resumable:
                    update_hitl_session(db, session_id, "expired")
                    ctx = build_recovered_context(
                        session,
                        default_device_id=config.network.device_id,
                    )
                    if client.ws and not getattr(client.ws, "closed", False):
                        await _send_agent_reply(
                            "先前危险操作审批已失效（Agent 状态已丢失），请重新发送指令。",
                            target_device_id=ctx.device_id,
                            target_user_id=ctx.device_id,
                        )
                    logger.warning(
                        "HITL 不可恢复，已过期: task=%s thread=%s",
                        task_id,
                        thread_id,
                    )
                    continue

                pending = _register_recovered_session(session)
                if pending is None:
                    continue

                if client.ws and not getattr(client.ws, "closed", False):
                    hitl_msg = Message(
                        msg_type=MsgType.HITL_REQ,
                        device_id=config.network.device_id,
                        payload={
                            "task_id": task_id,
                            "description": session["description"],
                            "risk_level": session["risk_level"],
                            "recovered": True,
                            "resumable": True,
                            "target_device_id": pending.device_id,
                            "target_user_id": _pending_user_id(pending),
                        },
                    )
                    await client.send(hitl_msg)
                _schedule_hitl_watchdog(task_id, created_at)
                recovered += 1
                logger.warning(
                    "恢复未决 HITL: %s thread=%s resumable=True remaining=%.0fs",
                    task_id,
                    pending.thread_id,
                    remaining,
                )
            if recovered:
                logger.warning("GAP-002 恢复了 %d 个未决 HITL 会话（可 Command(resume)）", recovered)

        client.on_connected(on_connected)

        try:
            await client.start()
        except KeyboardInterrupt:
            logger.info("收到中断信号，正在退出...")
        finally:
            for task_id in list(hitl_watchdogs):
                _cancel_hitl_watchdog(task_id)
            if memory_warmup and not memory_warmup.done():
                memory_warmup.cancel()
            await client.stop()
            shutdown_observability()
            release_pid_lock()
            logger.info("Agent 已停止")


def cli(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    if args.stop:
        sys.exit(0 if stop_running_agent() else 1)

    if args.status:
        pid = agent_status()
        if pid is None:
            print("Agent 未运行")
            sys.exit(1)
        print(f"Agent 运行中 (PID={pid})")
        sys.exit(0)

    asyncio.run(main(args.config_path))


if __name__ == "__main__":
    cli()
