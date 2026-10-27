"""Gateway-facing agent host.

Transport, sessions, files, and HITL live here. A chat turn or a Skill
delegates to `runtime.decision`, which is the one place a run is defined.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import structlog.contextvars

from lingji_agent.cognitive.orchestrator import build_run_config
from lingji_agent.cognitive.session_history import load_thread_ui_history
from lingji_agent.execution.hitl import (
    build_recovered_context,
    find_pending_hitl_for_thread,
    hitl_remaining_seconds,
    register_recovered_pending_run,
    thread_has_pending_hitl,
)
from lingji_agent.foundation import run_metrics
from lingji_agent.foundation.logger import get_logger
from lingji_agent.foundation.db import (
    _session_title,
    expire_hitl_session_by_task_id,
    get_active_chat_thread,
    get_chat_session,
    get_pending_hitl_session_by_task_id,
    get_pending_hitl_sessions_with_checkpoints,
    list_chat_sessions,
    set_active_chat_session,
    update_hitl_session,
    upsert_chat_session,
)
from lingji_agent.foundation.scheduler import is_scheduler_agent
from lingji_agent.network.file_registry_client import register_lingji_file
from lingji_agent.network.file_upload import upload_file_to_gateway
from lingji_agent.network.fleet_client import request_fleet_transfer
from lingji_agent.network.fleet_resolve import fetch_online_agents
from lingji_agent.network.incoming_files import (
    format_saved_reply,
    format_upload_errors,
    save_uploads_to_pc,
    should_upload_fastpath,
    uploads_all_saved,
)
from lingji_agent.network.lingji_file_format import append_lf_id_block, lingji_files_payload
from lingji_agent.network.protocol import Message, MsgType, build_agent_res_payload
from lingji_agent.network.router import Router
from lingji_agent.observability.tracing import trace_span
from lingji_agent.runtime.decision import resume_text_decision, run_job_decision, run_text_decision
from lingji_agent.runtime.types import PendingRun, format_tool_results, pending_user_id
from lingji_agent.runtime.web_client import resolve_web_client

logger = get_logger(__name__)


class AgentService:
    def __init__(self, config, db, graph, connector, registry, hitl, prompt, memory, memory_warmup):
        self.config = config
        self.db = db
        self.graph = graph
        self.connector = connector
        self.registry = registry
        self.hitl = hitl
        self.prompt = prompt
        self.memory = memory
        self.memory_warmup = memory_warmup
        self.client = None
        self.router = Router()
        self.pending_runs: dict[str, PendingRun] = {}
        self.hitl_watchdogs: dict[str, asyncio.Task] = {}
        self.hitl_resume_lock = asyncio.Lock()
        self.thread_run_locks: dict[str, asyncio.Lock] = {}
        self.device_active_threads: dict[str, str] = {}
        self.hitl_timeout_sec = float(config.security.hitl_timeout_sec)
        self._register_routes()

    def attach_client(self, client) -> None:
        self.client = client

    def _register_routes(self) -> None:
        self.router.register(MsgType.CMD_TEXT, self.handle_text)
        self.router.register(MsgType.CMD_LIST_SESSIONS, self.handle_list_sessions)
        self.router.register(MsgType.CMD_HERMES_SESSION, self.handle_hermes)
        self.router.register(MsgType.FLEET_DELIVER, self.handle_fleet_deliver)
        self.router.register(MsgType.FLEET_RELAY_BY_ID, self.handle_fleet_relay)
        self.router.register(MsgType.JOB_DELEGATE, self.handle_job)
        self.router.register(MsgType.HITL_REQ, self.handle_hitl_req)
        self.router.register(MsgType.HITL_RES, self.handle_hitl_res)

    def lock_for_thread(self, thread_id: str) -> asyncio.Lock:
        lock = self.thread_run_locks.get(thread_id)
        if lock is None:
            lock = asyncio.Lock()
            self.thread_run_locks[thread_id] = lock
        return lock

    async def send_reply(
        self,
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
        client = self.client
        if client and client.ws and not getattr(client.ws, "closed", False):
            await client.send(Message(
                msg_type=MsgType.AGENT_RES,
                device_id=self.config.network.device_id,
                payload=build_agent_res_payload(
                    reply_text,
                    attachments,
                    target_device_id=target_device_id or None,
                    **extra_payload,
                ),
            ))

    async def send_activity(
        self,
        phase: str,
        *,
        detail: str = "",
        target_device_id: str = "",
        target_user_id: str = "",
        thread_id: str = "",
        run_id: str = "",
    ) -> None:
        if not target_user_id and not target_device_id:
            return
        extra: dict = {"status": "activity", "phase": phase, "detail": detail or ""}
        if thread_id:
            extra["thread_id"] = thread_id
        if run_id:
            extra["run_id"] = run_id
        await self.send_reply(
            "",
            target_device_id=target_device_id,
            target_user_id=target_user_id,
            **extra,
        )

    def make_activity_reporter(self, conn_id: str, user_id: str, thread_id: str, run_id: str):
        async def report(phase: str, detail: str = "") -> None:
            await self.send_activity(
                phase,
                detail=detail,
                target_device_id=conn_id,
                target_user_id=user_id,
                thread_id=thread_id,
                run_id=run_id,
            )

        return report

    async def finalize_turn(self, result: dict, thread_id: str, user_text: str) -> str:
        reply_text = result.get("final_response", "（无回复）")
        tool_output = format_tool_results(result.get("tool_results", []))
        await self.memory.save_episodic_memory(thread_id=thread_id, role="user", content=user_text)
        await self.memory.save_episodic_memory(
            thread_id=thread_id,
            role="assistant",
            content=reply_text,
            tool_output=tool_output or None,
        )
        return reply_text

    def log_run_complete(self, pending: PendingRun | None, *, hitl_pending: int = 0) -> None:
        if pending is None:
            return
        import time

        duration_ms = (time.monotonic() - pending.run_started_at) * 1000
        run_metrics.increment("run_complete_total")
        run_metrics.record_run_duration(duration_ms / 1000.0)
        logger.info(
            "run_complete duration_ms=%.1f hitl_pending=%d device_id=%s",
            duration_ms,
            hitl_pending,
            pending.device_id,
        )

    async def thread_ui_history(self, thread_id: str) -> list[dict]:
        if not thread_id:
            return []
        return await load_thread_ui_history(
            self.graph,
            thread_id,
            connector=self.connector,
            registry=self.registry,
            hitl_manager=self.hitl,
            sanitizer_force_docker=self.config.security.sanitizer_force_docker,
        )

    async def reply_session_view(
        self,
        user_id: str,
        thread_id: str,
        *,
        connection_id: str,
        status: str,
        message: str = "",
    ) -> None:
        sessions = [
            {**row, "agent_id": self.config.network.device_id}
            for row in list_chat_sessions(self.db, user_id)
        ]
        history = await self.thread_ui_history(thread_id)
        pending_hitl = find_pending_hitl_for_thread(self.db, thread_id, self.pending_runs)
        extra: dict = {
            "status": status,
            "thread_id": thread_id,
            "sessions": sessions,
            "history": history,
        }
        if pending_hitl:
            extra["pending_hitl"] = {**pending_hitl, "agent_id": self.config.network.device_id}
        await self.send_reply(
            message,
            target_device_id=connection_id,
            target_user_id=user_id,
            **extra,
        )

    def resolve_thread_id(
        self,
        device_id: str,
        new_session: bool,
        switch_thread_id: str | None = None,
    ) -> tuple[str, bool]:
        active = self.device_active_threads
        if switch_thread_id:
            active[device_id] = switch_thread_id
            return switch_thread_id, True
        if device_id not in active:
            stored = get_active_chat_thread(self.db, device_id)
            if stored and not new_session:
                active[device_id] = stored
                return stored, True
        if new_session or device_id not in active:
            thread_id = f"{device_id}:{uuid.uuid4()}"
            active[device_id] = thread_id
            return thread_id, False
        return active[device_id], True

    async def build_fleet_context(self) -> str:
        agents = await fetch_online_agents(
            host=self.config.network.gateway_host,
            port=self.config.network.gateway_port,
            auth_token=self.config.network.auth_token,
        )
        local_name = self.config.network.display_name or self.config.network.device_id
        lines = [f"- {self.config.network.device_id}（本机 · {local_name}）"]
        for agent in agents:
            did = agent.get("device_id") or ""
            if not did or did == self.config.network.device_id:
                continue
            lines.append(f"- {did}（{agent.get('display_name') or did}）")
        lines.append("")
        lines.append(
            "常用别名：青铜剑/主PC/Primary PC → lingji-pc；"
            "空城记/笔记本/Laptop → lingji-laptop。"
            "fleet_send_file / relay_file_by_id 的 to_agent_id 可直接填别名。"
        )
        return "\n".join(lines)

    def command_context_from_payload(self, payload: dict) -> str:
        entry = payload.get("command_agent_id") or payload.get("target_agent_id") or ""
        if not entry:
            return ""
        local = self.config.network.display_name or self.config.network.device_id
        lines = [
            f"用户当前从入口设备 {entry} 发令；"
            f"本机 Agent 为 {self.config.network.device_id}（{local}）。"
        ]
        if is_scheduler_agent():
            lines.append(
                "本机为调度 Agent：对用户负责，跨机/运维任务应建 LJ-* Job 并委派值守机（青铜剑 lingji-pc）执行。"
            )
        elif self.config.scheduler.scheduler_agent_id:
            sched = self.config.scheduler.scheduler_agent_id
            lines.append(
                f"本机为值守执行机；用户对话面为调度 Agent（{sched}）。"
                "勿代替调度 Agent 对用户做总体承诺。"
            )
        return "\n".join(lines)

    def build_scheduler_context(self) -> str:
        if is_scheduler_agent():
            guardians = self.config.scheduler.guardian_executor_ids or ["lingji-pc"]
            return (
                f"本机 {self.config.network.device_id} 是用户的**秘书（调度 Agent）**。"
                f"值守执行机：{'、'.join(guardians)}。"
                "跨机传文件用 fleet_send_file；运维用 job_invoke(playbook=agent.status 等)。编码用 job_invoke_coding。"
                "禁止本机 execute_command 做 find/重启/发给青铜剑。"
                "对用户给一句话结案并带 LJ-*。"
                "值守机 CRITICAL 在进行中 Job 的 approval_scope 内由系统代批，不要再问用户确认。"
            )
        sched = (self.config.scheduler.scheduler_agent_id or "").strip()
        if sched and sched != self.config.network.device_id:
            return (
                f"本机 {self.config.network.device_id} 是**工位分机（执行机）**。"
                f"用户对话面为秘书 {sched}。收到 JOB_DELEGATE 后跑 playbook 并 REPORT，"
                "勿越权替秘书对用户说话。"
            )
        return ""

    async def register_uploads(self, user_id: str, upload_results: list[dict]) -> list[dict]:
        lingji_files: list[dict] = []
        net = self.config.network
        for item in upload_results:
            if not item.get("path"):
                continue
            registered = await register_lingji_file(
                user_id=user_id,
                name=item.get("name", "file"),
                holder_agent_id=net.device_id,
                local_path=item.get("path", ""),
                size_bytes=int(item.get("size_bytes") or 0),
                mime=item.get("mime", "application/octet-stream"),
                gateway_file_id=item.get("gateway_file_id", ""),
                source_agent_id=net.device_id,
                host=net.gateway_host,
                port=net.gateway_port,
                auth_token=net.auth_token,
            )
            lf_id = registered.get("lingji_file_id", "")
            if lf_id:
                item["lingji_file_id"] = lf_id
                lingji_files.append({"lingji_file_id": lf_id, "name": item.get("name", "file")})
        return lingji_files

    async def handle_text(self, msg: Message) -> None:
        user_text = msg.payload.get("text", "")
        uploads = msg.payload.get("uploads") or []
        conn_id, user_id = resolve_web_client(msg)
        device_id = user_id
        new_session = bool(msg.payload.get("new_session"))
        switch_thread_id = msg.payload.get("thread_id") or None
        upload_deferred = False
        run_id = str(uuid.uuid4())
        import time

        run_started_at = time.monotonic()
        structlog.contextvars.bind_contextvars(run_id=run_id, device_id=device_id)
        try:
            with trace_span("agent.run", {"run_id": run_id, "device_id": device_id}):
                run_metrics.increment("cmd_total")
                logger.info("📱 [%s] %s", device_id, user_text[:120] if user_text else "(upload/switch)")
                session_title = self._session_title(device_id, new_session, switch_thread_id)
                if await self._maybe_switch_session(
                    conn_id, user_id, device_id, new_session, switch_thread_id, uploads, user_text,
                ):
                    return
                user_text, upload_deferred, stop = await self._accept_uploads(
                    user_text,
                    uploads,
                    conn_id,
                    user_id,
                    device_id,
                    new_session,
                    switch_thread_id,
                    session_title,
                )
                if stop:
                    return
                thread_id, continue_thread = self.resolve_thread_id(
                    device_id, new_session, switch_thread_id,
                )
                if new_session:
                    logger.info("新对话 session thread=%s device=%s", thread_id, device_id)
                self._touch_session(device_id, thread_id, user_text, new_session, switch_thread_id)
                if not user_text.strip():
                    return
                if thread_has_pending_hitl(self.db, thread_id, self.pending_runs):
                    await self.send_reply(
                        "⏳ 当前会话仍有危险操作等待审批，请在任意已登录设备点击顶部批准条（或拒绝）后再发送新消息。",
                        target_device_id=conn_id,
                        target_user_id=user_id,
                    )
                    return
                await run_text_decision(
                    self,
                    user_text=user_text,
                    thread_id=thread_id,
                    continue_thread=continue_thread,
                    conn_id=conn_id,
                    user_id=user_id,
                    run_id=run_id,
                    run_started_at=run_started_at,
                    upload_deferred=upload_deferred,
                    payload=msg.payload,
                )
        finally:
            structlog.contextvars.unbind_contextvars("run_id", "device_id")

    async def _maybe_switch_session(
        self, conn_id, user_id, device_id, new_session, switch_thread_id, uploads, user_text,
    ) -> bool:
        is_switch = bool(switch_thread_id) and not user_text.strip() and not uploads and not new_session
        if not is_switch:
            return False
        thread_id, _continue = self.resolve_thread_id(device_id, new_session, switch_thread_id)
        set_active_chat_session(self.db, device_id, thread_id)
        await self.reply_session_view(
            user_id, thread_id, connection_id=conn_id, status="session_switched",
        )
        return True

    def _session_title(self, device_id: str, new_session: bool, switch_thread_id) -> str:
        if new_session:
            return ""
        lookup_tid = (switch_thread_id or "").strip() or self.device_active_threads.get(device_id, "")
        if not lookup_tid:
            return ""
        row = get_chat_session(self.db, lookup_tid)
        return (row or {}).get("title") or ""

    async def _accept_uploads(
        self,
        user_text,
        uploads,
        conn_id,
        user_id,
        device_id,
        new_session,
        switch_thread_id,
        session_title: str,
    ) -> tuple[str, bool, bool]:
        if not uploads:
            return user_text, False, False
        net = self.config.network
        upload_block, upload_results = await save_uploads_to_pc(
            uploads,
            incoming_dir=net.incoming_dir,
            gateway_host=net.gateway_host,
            gateway_port=net.gateway_port,
            auth_token=net.auth_token,
        )
        if not uploads_all_saved(upload_results, len(uploads)):
            await self.send_reply(
                format_upload_errors(upload_results),
                target_device_id=conn_id,
                target_user_id=user_id,
            )
            return user_text, False, True
        plain_text = user_text.strip()
        if should_upload_fastpath(plain_text, session_title=session_title):
            run_metrics.increment("upload_fastpath_total")
            thread_id, _continue = self.resolve_thread_id(device_id, new_session, switch_thread_id)
            title = plain_text or upload_results[0].get("name", "上传文件")
            upsert_chat_session(
                self.db, device_id, thread_id, _session_title(title), set_active=True,
            )
            lingji_files = await self.register_uploads(user_id, upload_results)
            await self.send_reply(
                append_lf_id_block(format_saved_reply(upload_results), lingji_files),
                target_device_id=conn_id,
                target_user_id=user_id,
                thread_id=thread_id,
                **lingji_files_payload(lingji_files),
            )
            return user_text, False, True
        merged = f"{plain_text}\n\n{upload_block}".strip() if plain_text else upload_block
        return merged, True, False

    def _touch_session(self, device_id, thread_id, user_text, new_session, switch_thread_id) -> None:
        if user_text.strip() or new_session:
            upsert_chat_session(
                self.db,
                device_id,
                thread_id,
                _session_title(user_text) if user_text.strip() else "新对话",
                set_active=True,
            )
        elif switch_thread_id:
            set_active_chat_session(self.db, device_id, thread_id)

    async def handle_list_sessions(self, msg: Message) -> None:
        conn_id, user_id = resolve_web_client(msg)
        sessions = [
            {**row, "agent_id": self.config.network.device_id}
            for row in list_chat_sessions(self.db, user_id)
        ]
        active_tid = next((row["thread_id"] for row in sessions if row.get("active")), None)
        if not active_tid:
            active_tid = get_active_chat_thread(self.db, user_id)
        if active_tid:
            await self.reply_session_view(
                user_id, active_tid, connection_id=conn_id, status="sessions", message="",
            )
            return
        await self.send_reply(
            "",
            target_device_id=conn_id,
            target_user_id=user_id,
            status="sessions",
            sessions=sessions,
            history=[],
        )

    async def handle_hermes(self, msg: Message) -> None:
        from lingji_agent.execution.hermes_session import handle_hermes_session

        conn_id, user_id = resolve_web_client(msg)
        payload = msg.payload or {}
        action = str(payload.get("action") or "health")
        text = str(payload.get("text") or "")
        try:
            result = await asyncio.to_thread(
                handle_hermes_session, action, cfg=self.config.hermes_session, text=text,
            )
        except Exception as exc:
            logger.exception("hermes_session failed action=%s", action)
            result = {
                "action": action,
                "unimplemented": False,
                "ok": False,
                "hermes_status": "off",
                "channel_ready": False,
                "reason": f"控制面异常：{exc}",
            }
        status = "hermes_chat" if result.get("action") == "chat" else "hermes_session"
        logger.info(
            "hermes_session action=%s status=%s hermes_status=%s channel_ready=%s",
            result.get("action"),
            status,
            result.get("hermes_status"),
            result.get("channel_ready"),
        )
        await self.send_reply(
            "",
            target_device_id=conn_id,
            target_user_id=user_id,
            **result,
            status=status,
        )

    async def handle_fleet_deliver(self, msg: Message) -> None:
        uploads = msg.payload.get("uploads") or []
        transfer_id = msg.payload.get("transfer_id", "")
        user_id = msg.payload.get("user_id", "")
        thread_id = msg.payload.get("thread_id", "")
        from_agent = msg.payload.get("from_agent_id", "")
        net = self.config.network
        if not uploads:
            ack_payload = {
                "transfer_id": transfer_id,
                "status": "error",
                "error": "payload 缺少 uploads",
                "from_agent_id": from_agent,
                "to_agent_id": net.device_id,
                "user_id": user_id,
                "thread_id": thread_id,
            }
        else:
            run_metrics.increment("fleet_deliver_total")
            _upload_block, upload_results = await save_uploads_to_pc(
                uploads,
                incoming_dir=net.incoming_dir,
                gateway_host=net.gateway_host,
                gateway_port=net.gateway_port,
                auth_token=net.auth_token,
            )
            if uploads_all_saved(upload_results, len(uploads)):
                run_metrics.increment("fleet_deliver_saved_total")
                lingji_files = await self.register_uploads(user_id, upload_results)
                ack_payload = {
                    "transfer_id": transfer_id,
                    "status": "ok",
                    "saved": [dict(item) for item in upload_results],
                    "from_agent_id": from_agent,
                    "to_agent_id": net.device_id,
                    "user_id": user_id,
                    "thread_id": thread_id,
                    "uploads": uploads,
                }
                if lingji_files:
                    ack_payload["lingji_files"] = lingji_files
                logger.info(
                    "Fleet 落盘成功 transfer=%s from=%s files=%d",
                    transfer_id, from_agent, len(upload_results),
                )
            else:
                ack_payload = {
                    "transfer_id": transfer_id,
                    "status": "error",
                    "error": format_upload_errors(upload_results),
                    "from_agent_id": from_agent,
                    "to_agent_id": net.device_id,
                    "user_id": user_id,
                    "thread_id": thread_id,
                    "uploads": uploads,
                }
                logger.warning("Fleet 落盘失败 transfer=%s: %s", transfer_id, ack_payload["error"])
        client = self.client
        if client and client.ws and not getattr(client.ws, "closed", False):
            await client.send(Message(
                msg_type=MsgType.FLEET_ACK,
                device_id=net.device_id,
                payload=ack_payload,
            ))

    async def handle_fleet_relay(self, msg: Message) -> None:
        lf_id = (msg.payload.get("lingji_file_id") or "").strip().upper()
        local_path = msg.payload.get("local_path") or ""
        name = msg.payload.get("name") or "file"
        to_agent = msg.payload.get("to_agent_id") or ""
        to_user = msg.payload.get("to_user_id") or ""
        user_id = msg.payload.get("user_id") or ""
        thread_id = msg.payload.get("thread_id") or ""
        if not lf_id or not local_path:
            logger.warning("FLEET_RELAY_BY_ID 缺少 lingji_file_id 或 local_path")
            return
        path = Path(local_path).expanduser()
        if not path.is_file():
            logger.error("FLEET_RELAY_BY_ID 本地文件不存在: %s", path)
            return
        net = self.config.network
        upload_result = await upload_file_to_gateway(
            path, host=net.gateway_host, port=net.gateway_port, auth_token=net.auth_token,
        )
        if upload_result.get("error"):
            logger.error("FLEET_RELAY_BY_ID 上传失败: %s", upload_result["error"])
            return
        attachment = {
            "file_id": upload_result.get("file_id", ""),
            "name": name,
            "size_bytes": upload_result.get("size_bytes", 0),
            "mime": upload_result.get("mime", "application/octet-stream"),
            "download_path": upload_result.get("download_path", ""),
        }
        await register_lingji_file(
            user_id=user_id,
            name=name,
            holder_agent_id=net.device_id,
            local_path=str(path),
            size_bytes=attachment.get("size_bytes", 0),
            mime=attachment.get("mime", ""),
            gateway_file_id=attachment.get("file_id", ""),
            source_agent_id=net.device_id,
            lingji_file_id=lf_id,
            host=net.gateway_host,
            port=net.gateway_port,
            auth_token=net.auth_token,
        )
        transfer = await request_fleet_transfer(
            from_agent_id=net.device_id,
            to_agent_id=to_agent,
            to_user_id=to_user,
            thread_id=thread_id,
            user_id=user_id,
            uploads=[attachment],
            host=net.gateway_host,
            port=net.gateway_port,
            auth_token=net.auth_token,
        )
        logger.info(
            "FLEET_RELAY_BY_ID %s → agent=%s user=%s status=%s",
            lf_id, to_agent or "-", to_user or "-", transfer.get("status"),
        )

    async def handle_job(self, msg: Message) -> None:
        payload = msg.payload or {}
        executor = (payload.get("executor_id") or "").strip()
        if executor and executor != self.config.network.device_id:
            return
        await run_job_decision(self, payload)

    async def handle_hitl_req(self, msg: Message) -> None:
        if not is_scheduler_agent():
            return
        from lingji_agent.execution.delegated_hitl import handle_scheduler_hitl_req
        from lingji_agent.network.job_client import get_job

        action = await handle_scheduler_hitl_req(
            dict(msg.payload or {}),
            send=self.client.send,
            get_job=get_job,
            device_id=self.config.network.device_id,
        )
        payload = msg.payload or {}
        if action == "approved":
            logger.info("delegated HITL approved task=%s job=%s", payload.get("task_id"), payload.get("job_id"))
        elif action == "escalate_user":
            logger.info(
                "delegated HITL escalate user task=%s job=%s",
                payload.get("task_id"),
                payload.get("job_id"),
            )

    async def handle_hitl_res(self, msg: Message) -> None:
        decision = msg.payload.get("decision", "rejected")
        task_id = msg.payload.get("task_id", "")
        logger.info("HITL 审批: %s -> %s", task_id, decision)
        conn_id, user_id = resolve_web_client(msg)
        await self.resume_from_hitl(
            task_id, decision, hint_device_id=conn_id, hint_user_id=user_id,
        )

    def cancel_hitl_watchdog(self, task_id: str) -> None:
        task = self.hitl_watchdogs.pop(task_id, None)
        if task and not task.done():
            task.cancel()

    def schedule_hitl_watchdog(self, task_id: str, created_at: str | None = None) -> None:
        remaining = hitl_remaining_seconds(created_at, self.hitl_timeout_sec)
        if remaining <= 0:
            asyncio.create_task(self.resume_from_hitl(task_id, "timeout"))
            return
        self.cancel_hitl_watchdog(task_id)
        self.hitl_watchdogs[task_id] = asyncio.create_task(
            self._hitl_timeout_watch(task_id, remaining),
            name=f"hitl-timeout-{task_id}",
        )

    async def _hitl_timeout_watch(self, task_id: str, delay_sec: float | None = None) -> None:
        try:
            await asyncio.sleep(delay_sec if delay_sec is not None else self.hitl_timeout_sec)
            if task_id not in self.pending_runs:
                return
            logger.warning("HITL 审批超时: task=%s", task_id)
            run_metrics.increment("hitl_timeout_total")
            await self.resume_from_hitl(task_id, "timeout")
        except asyncio.CancelledError:
            pass

    async def hitl_job_fields(self, user_id: str, tool: str, args: dict) -> dict:
        from lingji_agent.execution.delegated_hitl import attach_job_fields, pick_job_from_list
        from lingji_agent.network.job_client import list_jobs

        job = None
        try:
            data = await list_jobs(user_id)
            job = pick_job_from_list(data.get("jobs") or [], self.config.network.device_id)
        except Exception as exc:
            logger.warning("HITL bind job failed: %s", exc)
        return attach_job_fields(job, tool, args, executor_id=self.config.network.device_id)

    async def send_hitl_requests(self, result: dict, pending: PendingRun) -> None:
        from lingji_agent.cognitive.orchestrator import extract_interrupt_payloads

        for payload in extract_interrupt_payloads(result):
            task_id = payload.get("task_id", "")
            if not task_id:
                continue
            self.pending_runs[task_id] = pending
            run_metrics.increment("hitl_interrupt_total")
            tool = payload.get("tool", "") or ""
            args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
            user_id = pending.user_id or pending.device_id
            extra = await self.hitl_job_fields(user_id, tool, args)
            client = self.client
            if client and client.ws and not getattr(client.ws, "closed", False):
                hitl_payload = {
                    "task_id": task_id,
                    "description": payload.get("description", ""),
                    "risk_level": "critical",
                    "tool": tool,
                    "tool_args": args,
                    "thread_id": pending.thread_id,
                    "agent_id": self.config.network.device_id,
                    "target_device_id": pending.device_id,
                    "target_user_id": user_id,
                }
                hitl_payload.update(extra)
                await client.send(Message(
                    msg_type=MsgType.HITL_REQ,
                    device_id=self.config.network.device_id,
                    payload=hitl_payload,
                ))
                logger.info(
                    "已发送 HITL_REQ: task=%s escalation=%s job=%s",
                    task_id, extra.get("escalation"), extra.get("job_id"),
                )
                if extra.get("escalation") != "scheduler":
                    await self.send_activity(
                        "waiting_hitl",
                        detail=tool,
                        target_device_id=pending.device_id,
                        target_user_id=user_id,
                        thread_id=pending.thread_id,
                    )
            self.cancel_hitl_watchdog(task_id)
            self.schedule_hitl_watchdog(task_id)

    async def graph_has_interrupt(self, thread_id: str) -> bool:
        run_config = build_run_config(
            thread_id=thread_id,
            connector=self.connector,
            registry=self.registry,
            hitl_manager=self.hitl,
            sanitizer_force_docker=self.config.security.sanitizer_force_docker,
        )
        try:
            snap = await self.graph.aget_state(run_config)
        except Exception as exc:
            logger.warning("GAP-002 读取 graph 状态失败 thread=%s: %s", thread_id, exc)
            return False
        return bool(snap and snap.interrupts)

    def register_recovered_session(self, session: dict) -> PendingRun | None:
        try:
            return register_recovered_pending_run(
                self.pending_runs,
                session,
                PendingRun,
                default_device_id=self.config.network.device_id,
            )
        except Exception as exc:
            logger.error("GAP-002 恢复 pending run 失败 task=%s: %s", session.get("task_id"), exc)
            return None

    async def ensure_pending_run(self, task_id: str) -> PendingRun | None:
        if task_id in self.pending_runs:
            return self.pending_runs[task_id]
        session = get_pending_hitl_session_by_task_id(self.db, task_id)
        if not session:
            return None
        pending = self.register_recovered_session(session)
        if pending and await self.graph_has_interrupt(pending.thread_id):
            self.schedule_hitl_watchdog(task_id, session.get("created_at"))
        return pending

    async def notify_hitl_resume_lost(
        self, task_id: str, *, target_device_id: str = "", target_user_id: str = "",
    ) -> None:
        device_id = target_device_id
        user_id = target_user_id
        if not device_id and not user_id:
            session = get_pending_hitl_session_by_task_id(self.db, task_id)
            if session:
                ctx = build_recovered_context(session, default_device_id=self.config.network.device_id)
                device_id = ctx.device_id
                if ctx.thread_id.startswith("user-"):
                    user_id = ctx.thread_id.split(":", 1)[0]
        short = f"{task_id[:12]}…" if len(task_id) > 12 else task_id
        await self.send_reply(
            f"⚠️ 审批（{short}）未能恢复执行：会话上下文已丢失（可能 Agent 曾重启）。请重新发送指令。",
            target_device_id=device_id,
            target_user_id=user_id,
            hitl_stale_task_id=task_id,
        )

    async def resume_from_hitl(
        self,
        task_id: str,
        decision: str,
        *,
        hint_device_id: str = "",
        hint_user_id: str = "",
    ) -> bool:
        async with self.hitl_resume_lock:
            self.cancel_hitl_watchdog(task_id)
            pending = await self.ensure_pending_run(task_id)
            if pending is None:
                logger.warning("HITL resume 失败: task=%s 无 pending 上下文", task_id)
                expire_hitl_session_by_task_id(self.db, task_id, "stale")
                await self.notify_hitl_resume_lost(
                    task_id, target_device_id=hint_device_id, target_user_id=hint_user_id,
                )
                return True
            if not await self.graph_has_interrupt(pending.thread_id):
                logger.error("GAP-002: thread=%s 无 LangGraph interrupt，无法 Command(resume)", pending.thread_id)
                expire_hitl_session_by_task_id(self.db, task_id, "stale")
                await self.send_reply(
                    "❌ 无法恢复挂起的审批：Agent 状态已丢失，请重新发送指令。",
                    target_device_id=pending.device_id,
                    target_user_id=pending_user_id(pending),
                    hitl_stale_task_id=task_id,
                )
                self.hitl.resolve_interrupt(task_id, "error")
                self.pending_runs.pop(task_id, None)
                return True

            self.hitl.resolve_interrupt(task_id, decision)
            self.pending_runs.pop(task_id, None)
            resume_run_id = str(uuid.uuid4())
            activity = self.make_activity_reporter(
                pending.device_id, pending_user_id(pending), pending.thread_id, resume_run_id,
            )
            await activity("thinking")
            try:
                finished, payload = await resume_text_decision(self, pending, decision, activity)
            except Exception as exc:
                run_metrics.increment("agent_errors")
                logger.error("HITL 恢复执行失败: %s", exc)
                await self.send_reply(
                    f"❌ HITL 恢复失败：{exc}",
                    target_device_id=pending.device_id,
                    target_user_id=pending_user_id(pending),
                )
                await activity("idle")
                self.log_run_complete(pending)
                return True
            if not finished:
                await self.send_hitl_requests(payload or {}, pending)
                logger.info("Agent 再次挂起等待 HITL (thread=%s)", pending.thread_id)
                return False
            await self.send_reply(
                payload["reply"],
                payload.get("attachments"),
                target_device_id=pending.device_id,
                target_user_id=pending_user_id(pending),
            )
            await activity("idle")
            self.log_run_complete(pending)
            return True

    def on_connected(self) -> None:
        logger.info("已连接到灵机 Gateway")
        tools = [tool.name for tool in self.registry.list_all()]
        logger.info("可用工具: %s", ", ".join(tools) if tools else "（无）")
        asyncio.create_task(self.flush_restart_report())
        asyncio.create_task(self.recover_pending())
        asyncio.create_task(self.recover_orphan_coding())

    async def flush_restart_report(self) -> None:
        from lingji_agent.execution.pending_job_report import default_data_dir, flush_pending_report
        from lingji_agent.network.job_client import report_job_step

        net = self.config.network

        async def _reporter(job_id, step_id, *, status, evidence=None, error=""):
            return await report_job_step(
                job_id, step_id, status=status, evidence=evidence, error=error,
                host=net.gateway_host, port=net.gateway_port, auth_token=net.auth_token,
            )

        out = await flush_pending_report(default_data_dir(), reporter=_reporter)
        if out.get("skipped"):
            return
        logger.info("重启后补报: %s", out)

    async def recover_orphan_coding(self) -> None:
        from lingji_agent.execution.coding_supervisor import recover_orphan_coding_jobs
        from lingji_agent.network.job_client import report_job_step

        jobs_root = (self.config.coding.jobs_root or "").strip()
        if not jobs_root:
            return
        net = self.config.network

        async def _reporter(job_id, step_id, *, status, evidence=None, error=""):
            return await report_job_step(
                job_id, step_id, status=status, evidence=evidence, error=error,
                host=net.gateway_host, port=net.gateway_port, auth_token=net.auth_token,
            )

        items = await recover_orphan_coding_jobs(
            Path(jobs_root), report=_reporter, hung_sec=self.config.coding.hung_sec,
        )
        if items:
            logger.warning("coding orphan recover: %d executor_lost", len(items))

    async def recover_pending(self) -> None:
        sessions = get_pending_hitl_sessions_with_checkpoints(self.db)
        recovered = 0
        for session in sessions:
            task_id = session["task_id"]
            thread_id = session.get("thread_id") or ""
            session_id = session["id"]
            created_at = session.get("created_at")
            remaining = hitl_remaining_seconds(created_at, self.hitl_timeout_sec)
            if remaining <= 0:
                update_hitl_session(self.db, session_id, "timeout")
                logger.warning("HITL 已超时，跳过恢复: task=%s", task_id)
                continue
            if not await self.graph_has_interrupt(thread_id):
                update_hitl_session(self.db, session_id, "expired")
                ctx = build_recovered_context(session, default_device_id=self.config.network.device_id)
                client = self.client
                if client and client.ws and not getattr(client.ws, "closed", False):
                    await self.send_reply(
                        "先前危险操作审批已失效（Agent 状态已丢失），请重新发送指令。",
                        target_device_id=ctx.device_id,
                        target_user_id=ctx.device_id,
                    )
                logger.warning("HITL 不可恢复，已过期: task=%s thread=%s", task_id, thread_id)
                continue
            pending = self.register_recovered_session(session)
            if pending is None:
                continue
            client = self.client
            if client and client.ws and not getattr(client.ws, "closed", False):
                extra = await self.hitl_job_fields(pending_user_id(pending), session.get("tool") or "", {})
                rec_payload = {
                    "task_id": task_id,
                    "description": session["description"],
                    "risk_level": session["risk_level"],
                    "recovered": True,
                    "resumable": True,
                    "target_device_id": pending.device_id,
                    "target_user_id": pending_user_id(pending),
                    "agent_id": self.config.network.device_id,
                }
                rec_payload.update(extra)
                await client.send(Message(
                    msg_type=MsgType.HITL_REQ,
                    device_id=self.config.network.device_id,
                    payload=rec_payload,
                ))
            self.schedule_hitl_watchdog(task_id, created_at)
            recovered += 1
            logger.warning(
                "恢复未决 HITL: %s thread=%s resumable=True remaining=%.0fs",
                task_id, pending.thread_id, remaining,
            )
        if recovered:
            logger.warning("GAP-002 恢复了 %d 个未决 HITL 会话（可 Command(resume)）", recovered)

    def cancel_watchdogs(self) -> None:
        for task_id in list(self.hitl_watchdogs):
            self.cancel_hitl_watchdog(task_id)
