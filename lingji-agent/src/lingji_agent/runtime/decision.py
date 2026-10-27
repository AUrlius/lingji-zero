"""One decision, one trace.

`run_text_decision` is a chat turn: memory, injection check, the model and
its tools, then a hallucination check. `run_job_decision` is one Skill.
`resume_text_decision` continues the same trace after a human step.

Tools, permission, sandbox, tokens, and context compression are recorded by
the graph while this trace is open. Memory keep/drop is recorded when this
turn writes or prunes. Nothing here sets a numeric target.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langgraph.types import Command

from lingji_agent.cognitive.orchestrator import (
    build_run_config,
    has_interrupt,
    run_agent,
)
from lingji_agent.foundation import run_metrics
from lingji_agent.foundation.logger import get_logger
from lingji_agent.observability.decision_trace import (
    DecisionTrace,
    bound_trace,
    decision_run,
)
from lingji_agent.observability.tracing import add_span_event
from lingji_agent.runtime.types import PendingRun, decision_succeeded
from lingji_agent.security.hallucination import run_hallucination_check

if TYPE_CHECKING:
    from lingji_agent.runtime.service import AgentService

logger = get_logger(__name__)


async def run_text_decision(
    svc: AgentService,
    *,
    user_text: str,
    thread_id: str,
    continue_thread: bool,
    conn_id: str,
    user_id: str,
    run_id: str,
    run_started_at: float,
    upload_deferred: bool,
    payload: dict,
) -> None:
    """Run one chat decision and answer on the gateway."""
    activity = svc.make_activity_reporter(conn_id, user_id, thread_id, run_id)
    if svc.memory_warmup and not svc.memory_warmup.done():
        await svc.memory_warmup
    if upload_deferred:
        await activity("received")
    await activity("thinking")

    with decision_run(run_id) as trace:
        retrieved = svc.memory.retrieve_context(
            user_text,
            episodic_thread_id=thread_id,
        )
        if svc.config.security.guardrails_enabled:
            from lingji_agent.security.guardrails import SecurityGuardrail

            guardrail = SecurityGuardrail()
            verdict = guardrail.inspect(user_text, context=retrieved)
            if not verdict.allowed:
                logger.warning(
                    "guardrail_blocked rule_id=%s reason=%s",
                    verdict.rule_id,
                    verdict.reason,
                )
                add_span_event(
                    "security.blocked",
                    {"rule_id": verdict.rule_id, "reason": verdict.reason},
                )
                if svc.config.security.guardrails_block:
                    run_metrics.increment(
                        "guardrail_blocked_total",
                        rule_id=verdict.rule_id,
                    )
                    trace.finish(success=False)
                    await svc.send_reply(
                        SecurityGuardrail.block_message(verdict),
                        target_device_id=conn_id,
                        target_user_id=user_id,
                    )
                    await activity("idle")
                    return

        system_prompt = svc.prompt.build_system_prompt(
            retrieved_memory_context=retrieved,
            fleet_context=await svc.build_fleet_context(),
            command_context=svc.command_context_from_payload(payload),
            scheduler_context=svc.build_scheduler_context(),
        )
        pending = PendingRun(
            thread_id=thread_id,
            device_id=conn_id,
            user_id=user_id,
            user_text=user_text,
            system_prompt=system_prompt,
            run_started_at=run_started_at,
            trace_id=trace.trace_id,
        )
        attachments: list[dict] | None = None
        try:
            async with svc.lock_for_thread(thread_id):
                result = await run_agent(
                    graph=svc.graph,
                    user_message=user_text,
                    system_prompt=system_prompt,
                    connector=svc.connector,
                    registry=svc.registry,
                    thread_id=thread_id,
                    user_id=user_id,
                    hitl_manager=svc.hitl,
                    sanitizer_force_docker=svc.config.security.sanitizer_force_docker,
                    continue_thread=continue_thread,
                    activity_reporter=activity,
                )
            if has_interrupt(result):
                trace.note_human_step()
                await svc.send_hitl_requests(result, pending)
                logger.info("Agent 挂起等待 HITL 审批 (thread=%s)", thread_id)
                trace.checkpoint()
                return
            reply_text = await svc.finalize_turn(result, thread_id, user_text)
            attachments = result.get("attachments") or None
            run_hallucination_check(reply_text, retrieved)
            trace.finish(success=decision_succeeded(reply_text))
        except Exception as exc:
            run_metrics.increment("agent_errors")
            logger.error("Agent 执行失败: %s", exc)
            reply_text = f"❌ AI 服务暂不可用，请稍后重试。\n\n错误详情：{exc}"
            trace.finish(success=False)

        await svc.send_reply(
            reply_text,
            attachments,
            target_device_id=conn_id,
            target_user_id=user_id,
            thread_id=thread_id,
        )
        await activity("idle")
        svc.log_run_complete(pending)


async def resume_text_decision(
    svc: AgentService,
    pending: PendingRun,
    decision: str,
    activity,
) -> tuple[bool, dict[str, Any] | None]:
    """Continue the same decision after a person answers. False means it paused again."""
    trace = DecisionTrace.attach(pending.trace_id) if pending.trace_id else None
    if trace is None:
        trace = DecisionTrace.begin()
        trace.note_human_step()
    pending.trace_id = trace.trace_id
    from lingji_agent.runtime.types import pending_user_id

    with bound_trace(trace):
        run_config = build_run_config(
            thread_id=pending.thread_id,
            connector=svc.connector,
            registry=svc.registry,
            hitl_manager=svc.hitl,
            sanitizer_force_docker=svc.config.security.sanitizer_force_docker,
            user_id=pending_user_id(pending),
            activity_reporter=activity,
        )
        result = await svc.graph.ainvoke(Command(resume=decision), run_config)
        if has_interrupt(result):
            trace.note_human_step()
            trace.checkpoint()
            return False, result
        reply_text = await svc.finalize_turn(result, pending.thread_id, pending.user_text)
        run_hallucination_check(reply_text, pending.system_prompt)
        trace.finish(success=decision_succeeded(reply_text))
        return True, {
            "reply": reply_text,
            "attachments": result.get("attachments") or None,
        }


async def run_job_decision(svc: AgentService, payload: dict) -> None:
    """One delegated Skill. Permission rejection is a failed decision."""
    playbook_id = payload.get("playbook_id") or ""
    job_id = payload.get("job_id") or ""
    step_id = payload.get("step_id") or ""
    with decision_run() as trace:
        if playbook_id:
            trace.note_skill(playbook_id)
        if str(playbook_id).startswith("coding."):
            await _run_coding_skill(svc, payload, trace)
            return
        await _run_playbook_skill(svc, playbook_id, job_id, step_id, payload, trace)


async def _run_coding_skill(svc: AgentService, payload: dict, trace: DecisionTrace) -> None:
    from lingji_agent.execution.coding_supervisor import handle_job_delegate
    from lingji_agent.network.job_client import get_job, report_job_step

    playbook_id = payload.get("playbook_id") or ""
    outcome: list[bool] = []

    async def _report(reported_job_id, reported_step_id, *, status, evidence=None, error="", **kwargs):
        err = str(error or "")
        ev = evidence if isinstance(evidence, dict) else {}
        if status == "failed" and (
            ev.get("reason") == "scope"
            or "approval_scope" in err
            or err == "source_git not allowed"
        ):
            trace.note_tool_blocked(permission=True, tool=playbook_id)
        if status == "completed":
            outcome.append(True)
        elif status == "failed":
            outcome.append(False)
        return await report_job_step(
            reported_job_id,
            reported_step_id,
            status=status,
            evidence=evidence,
            error=error,
            **kwargs,
        )

    try:
        await handle_job_delegate(payload, svc.config.coding, report=_report, get_job=get_job)
    except Exception:
        trace.finish(success=False)
        raise
    trace.finish(success=bool(outcome[-1]) if outcome else False)


async def _run_playbook_skill(
    svc: AgentService,
    playbook_id: str,
    job_id: str,
    step_id: str,
    payload: dict,
    trace: DecisionTrace,
) -> None:
    from lingji_agent.execution.approval_scope import validate_playbook
    from lingji_agent.execution.pending_job_report import (
        clear_pending,
        default_data_dir,
        should_defer_report,
        write_pending,
    )
    from lingji_agent.execution.playbook_runner import run_playbook
    from lingji_agent.network.job_client import report_job_step

    scope = payload.get("approval_scope")
    ok, reason = validate_playbook(scope if isinstance(scope, dict) else None, playbook_id)
    if not ok:
        logger.warning("JOB_DELEGATE scope reject job=%s: %s", job_id, reason)
        trace.note_tool_blocked(permission=True, tool=playbook_id)
        trace.finish(success=False)
        await report_job_step(job_id, step_id, status="failed", error=reason)
        return

    logger.info("JOB_DELEGATE run playbook=%s job=%s", playbook_id, job_id)
    if should_defer_report(playbook_id):
        write_pending(
            default_data_dir(),
            job_id=job_id,
            step_id=step_id,
            playbook_id=playbook_id,
            evidence={"deferred": True},
        )
        logger.info("JOB_DELEGATE defer report until restart job=%s", job_id)
        result = await run_playbook(playbook_id)
        clear_pending(default_data_dir())
        await _report_playbook(job_id, step_id, result)
        trace.finish(success=bool(result.get("ok")))
        return

    result = await run_playbook(playbook_id)
    await _report_playbook(job_id, step_id, result)
    trace.finish(success=bool(result.get("ok")))


async def _report_playbook(job_id: str, step_id: str, result: dict) -> None:
    from lingji_agent.network.job_client import report_job_step

    if result.get("ok"):
        await report_job_step(job_id, step_id, status="completed", evidence=result)
        return
    await report_job_step(
        job_id,
        step_id,
        status="failed",
        evidence=result,
        error=str(result.get("error") or "playbook failed"),
    )
