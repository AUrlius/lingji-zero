"""LangGraph 状态机 — 认知层核心（Sprint 2 T-2.1/T-2.2）

节点: agent_think → [tool_executor ⇄ agent_think] → format_response

条件路由:
  - agent_think 返回 tool_calls → tool_executor
  - agent_think 返回 content → format_response
  - tool_executor 完成且未超轮次 → agent_think（继续思考）
  - tool_executor 完成且超轮次 → format_response
"""

import json
import logging
import time
from typing import Any, Literal, NotRequired, TypedDict

from langgraph.graph import StateGraph, END
from langgraph.config import get_config
from langgraph.types import interrupt

from lingji_agent.cognitive.llm_provider import ILLMConnector
from lingji_agent.execution.registry import ToolRegistry, RiskLevel
from lingji_agent.execution.hitl import HITLManager, HITLDecision
from lingji_agent.observability.metrics import record_llm_usage
from lingji_agent.observability.tracing import trace_span

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5  # 防止无限循环
MAX_CONTEXT_MESSAGES = 40  # 续聊时保留的非 system 消息上限（约 20 轮）


# ── 状态定义 ──────────────────────────────────────────────

class AgentState(TypedDict):
    messages: list[dict[str, Any]]       # 完整对话历史（含 tool 消息）
    tool_calls: list[dict[str, Any]]     # LLM 返回的待执行工具调用
    tool_results: list[dict[str, Any]]   # 工具执行结果
    final_response: str                  # 最终回复文本
    tool_round: int                      # 当前工具调用轮次
    attachments: NotRequired[list[dict[str, Any]]]  # G6 远程文件附件
    force_docker_sandbox: NotRequired[bool]  # sanitizer 威胁 → 强制 Docker（专利 5）


# ── 节点函数 ──────────────────────────────────────────────

async def _invoke_tool(
    tool_def,
    fn_args: dict[str, Any],
    *,
    force_docker: bool,
) -> Any:
    """执行工具；CRITICAL 且威胁升级时在 Docker 隔离上下文中运行。"""
    from lingji_agent.execution.sandbox import sandbox_execution_context

    with sandbox_execution_context(force_docker=force_docker):
        return await tool_def.fn(**fn_args)


async def agent_think(state: AgentState) -> AgentState:
    """LLM 推理节点：调用 LLM，解析 tool_calls 或文本回复"""
    cfg = get_config()
    configurable = cfg.get("configurable", {}) if cfg else {}
    connector: ILLMConnector = configurable.get("_connector")
    if connector is None:
        return _error_state(state, "LLM 连接器未注入")
    with trace_span("agent_think", {"llm.model": connector.model_name}):
        return await _agent_think_impl(state, connector, configurable)


async def _agent_think_impl(
    state: AgentState,
    connector: ILLMConnector,
    configurable: dict,
) -> AgentState:
    step_start = time.monotonic()
    registry: ToolRegistry = configurable.get("_registry")

    tools_schema = registry.to_openai_schema() if registry else None

    logger.info(
        "[agent_think] 调用 LLM（%s），消息数=%d，工具数=%d",
        connector.model_name,
        len(state["messages"]),
        len(tools_schema) if tools_schema else 0,
    )

    # Sanitize messages before sending to LLM
    from lingji_agent.security.sanitizer import AdversarialTextSanitizer
    _sanitizer = AdversarialTextSanitizer()
    sanitizer_force_docker = configurable.get("_sanitizer_force_docker", True)
    force_docker_sandbox = bool(state.get("force_docker_sandbox", False))

    sanitized_messages = []
    for msg in state["messages"]:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            result_san = _sanitizer.sanitize(content)
            if result_san.threats_detected > 0:
                logger.warning(
                    "[agent_think] 检测到 %d 个威胁: %s",
                    result_san.threats_detected,
                    ", ".join(result_san.threats),
                )
                if sanitizer_force_docker:
                    force_docker_sandbox = True
                    logger.warning(
                        "[agent_think] 威胁检测触发 Docker 隔离升级（专利 5 联动）"
                    )
            sanitized_messages.append({**msg, "content": result_san.cleaned})
        else:
            sanitized_messages.append(msg)

    try:
        result = await connector.chat_completion(
            messages=sanitized_messages,
            tools=tools_schema if tools_schema else None,
            stream=True,
        )
    except Exception as e:
        logger.error("[agent_think] LLM 调用失败: %s", e)
        return _error_state(state, f"LLM 调用失败: {e}")

    content = result.get("content", "")
    tool_calls = result.get("tool_calls", [])
    usage = result.get("usage", {})
    record_llm_usage(connector.model_name, usage)

    logger.info(
        "[agent_think] 响应: content_len=%d, tool_calls=%d, tokens=%s",
        len(content), len(tool_calls), usage.get("total_tokens", "?"),
    )

    # 追加 assistant 消息到对话历史
    assistant_msg: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        assistant_msg["tool_calls"] = tool_calls

    new_messages = list(state["messages"]) + [assistant_msg]

    if tool_calls:
        # 有工具调用 → 路由到 tool_executor
        logger.info("[agent_think] step_ms=%.1f", (time.monotonic() - step_start) * 1000)
        return {
            **state,
            "messages": new_messages,
            "tool_calls": tool_calls,
            "tool_results": [],
            "final_response": "",
            "force_docker_sandbox": force_docker_sandbox,
        }
    else:
        # 纯文本回复 → 路由到 format_response
        if not content.strip():
            logger.warning("[agent_think] LLM 返回空内容且无 tool_calls")
        logger.info("[agent_think] step_ms=%.1f", (time.monotonic() - step_start) * 1000)
        return {
            **state,
            "messages": new_messages,
            "tool_calls": [],
            "final_response": content,
            "force_docker_sandbox": force_docker_sandbox,
        }


async def tool_executor(state: AgentState) -> AgentState:
    """工具执行节点：执行所有待处理 tool_calls，将结果追加到消息历史"""
    with trace_span("tool_executor", {"tool_round": state.get("tool_round", 0)}):
        return await _tool_executor_impl(state)


async def _tool_executor_impl(state: AgentState) -> AgentState:
    step_start = time.monotonic()
    cfg = get_config()
    configurable = cfg.get("configurable", {}) if cfg else {}
    registry: ToolRegistry = configurable.get("_registry")
    tool_calls = state.get("tool_calls", [])

    if not tool_calls:
        logger.warning("[tool_executor] 无待执行工具调用")
        return state

    results = []
    new_messages = list(state["messages"])
    sanitizer_force_docker = configurable.get("_sanitizer_force_docker", True)
    force_docker_for_critical = (
        sanitizer_force_docker and bool(state.get("force_docker_sandbox", False))
    )

    for tc in tool_calls:
        fn_name = tc.get("function", {}).get("name", "")
        fn_args_str = tc.get("function", {}).get("arguments", "{}")
        tc_id = tc.get("id", "")

        # 解析参数
        try:
            fn_args = json.loads(fn_args_str)
        except json.JSONDecodeError:
            fn_args = {}

        # 查找工具
        tool_def = registry.get(fn_name)
        if tool_def is None:
            err = f"工具未注册: {fn_name}"
            logger.warning("[tool_executor] %s", err)
            result_content = json.dumps({"error": err})
        else:
            # 风险检查
            risk = tool_def.risk
            hitl_enabled = configurable.get("_hitl_enabled", True)
            use_force_docker = force_docker_for_critical and risk == RiskLevel.CRITICAL

            if risk == RiskLevel.CRITICAL and hitl_enabled:
                hitl_mgr: HITLManager | None = configurable.get("_hitl_manager")
                thread_id = configurable.get("thread_id")
                use_interrupt = configurable.get("_use_interrupt", True) and bool(thread_id)

                if use_interrupt:
                    description = f"执行 {fn_name}({fn_args_str})"
                    logger.warning(
                        "[tool_executor] HITL interrupt: %s(%s)",
                        fn_name, fn_args_str,
                    )
                    if hitl_mgr:
                        hitl_mgr.record_interrupt(
                            task_id=tc_id,
                            description=description,
                            risk_level="critical",
                            thread_id=thread_id,
                            agent_state=dict(state),
                        )
                    decision = interrupt({
                        "task_id": tc_id,
                        "tool": fn_name,
                        "args": fn_args,
                        "description": description,
                    })
                    if decision != "approved":
                        result_content = json.dumps({
                            "error": (
                                f"操作 '{fn_name}' 已被 HITL 安全策略"
                                f"{'拒绝' if decision == 'rejected' else '超时自动拒绝'}。"
                            ),
                            "hitl_rejected": True,
                            "reason": decision,
                        }, ensure_ascii=False)
                    else:
                        logger.info("[tool_executor] HITL 审批通过: %s", fn_name)
                        try:
                            raw_result = await _invoke_tool(
                                tool_def, fn_args, force_docker=use_force_docker,
                            )
                            result_content = json.dumps(raw_result, ensure_ascii=False)
                        except Exception as e:
                            logger.error("[tool_executor] 工具 %s 执行失败: %s", fn_name, e)
                            result_content = json.dumps({"error": str(e)})
                elif hitl_mgr:
                    logger.warning(
                        "[tool_executor] HITL 挂起(legacy): %s(%s)",
                        fn_name, fn_args_str,
                    )
                    decision = await hitl_mgr.request_approval(
                        task_id=f"{tc_id}",
                        description=f"执行 {fn_name}({fn_args_str})",
                        risk_level="critical",
                        agent_state=dict(state),
                        thread_id=thread_id or "",
                    )
                    if decision.value == "approved":
                        logger.info("[tool_executor] HITL 审批通过: %s", fn_name)
                        try:
                            raw_result = await _invoke_tool(
                                tool_def, fn_args, force_docker=use_force_docker,
                            )
                            result_content = json.dumps(raw_result, ensure_ascii=False)
                        except Exception as e:
                            logger.error("[tool_executor] 工具 %s 执行失败: %s", fn_name, e)
                            result_content = json.dumps({"error": str(e)})
                    else:
                        result_content = json.dumps({
                            "error": f"操作 '{fn_name}' 已被 HITL 安全策略{'拒绝' if decision.value == 'rejected' else '超时自动拒绝'}。",
                            "hitl_rejected": True,
                            "reason": decision.value,
                        }, ensure_ascii=False)
                else:
                    # Degrade: no HITLManager available, fall back to old blocking behavior
                    logger.warning(
                        "[tool_executor] 🔴 危险操作被 HITL 拦截: %s(%s)",
                        fn_name, fn_args_str,
                    )
                    result_content = json.dumps({
                        "error": f"操作 '{fn_name}' 已被 HITL 安全策略拦截。"
                                 f"此操作需要审批才能执行。"
                                 f"请在任意已登录设备（手机或电脑浏览器）点击批准按钮后重试。",
                        "hitl_required": True,
                        "risk": "critical",
                    }, ensure_ascii=False)
            else:
                logger.info("[tool_executor] 执行: %s(%s)", fn_name, fn_args_str)
                if fn_name in ("fleet_send_file", "relay_file_by_id"):
                    fn_args.setdefault("thread_id", configurable.get("thread_id", ""))
                    fn_args.setdefault("user_id", configurable.get("_user_id", ""))
                with trace_span(f"tool.execute.{fn_name}", {"tool.name": fn_name}):
                    try:
                        raw_result = await _invoke_tool(
                            tool_def, fn_args, force_docker=use_force_docker,
                        )
                        result_content = json.dumps(raw_result, ensure_ascii=False)
                    except Exception as e:
                        logger.error("[tool_executor] 工具 %s 执行失败: %s", fn_name, e)
                        result_content = json.dumps({"error": str(e)})

        results.append({
            "tool_call_id": tc_id,
            "tool_name": fn_name,
            "result": result_content,
        })

        # 追加 tool 消息
        new_messages.append({
            "role": "tool",
            "tool_call_id": tc_id,
            "content": result_content,
        })

    new_round = state.get("tool_round", 0) + 1
    logger.info(
        "[tool_executor] 第 %d 轮完成，执行 %d 个工具 step_ms=%.1f",
        new_round, len(results), (time.monotonic() - step_start) * 1000,
    )

    return {
        **state,
        "messages": new_messages,
        "tool_results": results,
        "tool_calls": [],
        "tool_round": new_round,
    }


def _collect_attachments(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从 send_file_to_user / fleet_send_file(to_user) 工具结果合并 attachments（G6/Fleet）。"""
    attachments: list[dict[str, Any]] = []
    for item in tool_results:
        if item.get("tool_name") not in ("send_file_to_user", "fleet_send_file"):
            continue
        raw = item.get("result", "")
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            attachments.extend(parsed.get("attachments") or [])
    return attachments


def format_response(state: AgentState) -> AgentState:
    """格式化回复节点：提取最终回复文本（终点）"""
    with trace_span("format_response"):
        step_start = time.monotonic()
        final = state.get("final_response", "")
        if not final:
            for msg in reversed(state.get("messages", [])):
                if msg.get("role") == "assistant" and msg.get("content"):
                    final = msg["content"]
                    break

        attachments = _collect_attachments(state.get("tool_results", []))
        if attachments and not final:
            final = "文件已准备好，请点击下方下载。"

        logger.info(
            "[format_response] 最终回复: %d chars attachments=%d step_ms=%.1f",
            len(final), len(attachments), (time.monotonic() - step_start) * 1000,
        )
        return {**state, "final_response": final, "attachments": attachments}


# ── 条件路由函数 ──────────────────────────────────────────

def _route_after_think(state: AgentState) -> Literal["tool_executor", "format_response"]:
    """agent_think 之后：有 tool_calls → 执行，否则 → 回复"""
    if state.get("tool_calls"):
        return "tool_executor"
    return "format_response"


def _route_after_tool(state: AgentState) -> Literal["agent_think", "format_response"]:
    """tool_executor 之后：轮次未超 → 继续思考，超限 → 回复"""
    if state.get("tool_round", 0) >= MAX_TOOL_ROUNDS:
        logger.warning("[route] 工具调用已达最大轮次 %d，强制结束", MAX_TOOL_ROUNDS)
        return "format_response"
    return "agent_think"


# ── Graph 构建 ────────────────────────────────────────────

def build_graph(
    connector: ILLMConnector | None = None,
    registry: ToolRegistry | None = None,
    hitl_manager=None,
    checkpointer=None,
):
    """构建 LangGraph 状态机

    Args:
        connector: LLM 连接器（注入到 state._connector）
        registry: 工具注册表（注入到 state._registry）
        hitl_manager: HITL 管理器（注入到 state._hitl_manager）
        checkpointer: LangGraph checkpointer（启用 interrupt 挂起/恢复）
    """
    builder = StateGraph(AgentState)

    # 注册节点
    builder.add_node("agent_think", agent_think)
    builder.add_node("tool_executor", tool_executor)
    builder.add_node("format_response", format_response)

    # 入口 → agent_think
    builder.set_entry_point("agent_think")

    # agent_think → 条件分支
    builder.add_conditional_edges(
        "agent_think",
        _route_after_think,
        {
            "tool_executor": "tool_executor",
            "format_response": "format_response",
        },
    )

    # tool_executor → 条件分支（继续思考 or 结束）
    builder.add_conditional_edges(
        "tool_executor",
        _route_after_tool,
        {
            "agent_think": "agent_think",
            "format_response": "format_response",
        },
    )

    # format_response → END
    builder.add_edge("format_response", END)

    compile_kwargs = {}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer
    compiled = builder.compile(**compile_kwargs)

    # 将 connector 和 registry 注入到运行时（通过 configurable）
    compiled._connector = connector
    compiled._registry = registry
    compiled._hitl_manager = hitl_manager
    compiled._checkpointer = checkpointer

    return compiled


def has_interrupt(result: dict[str, Any]) -> bool:
    """检查 graph 结果是否处于 interrupt 挂起状态"""
    interrupts = result.get("__interrupt__")
    return bool(interrupts)


def extract_interrupt_payloads(result: dict[str, Any]) -> list[dict[str, Any]]:
    """从 graph 结果提取 interrupt payload 列表"""
    payloads: list[dict[str, Any]] = []
    for item in result.get("__interrupt__") or []:
        value = item.value if hasattr(item, "value") else item.get("value", item)
        if isinstance(value, dict):
            payloads.append(value)
    return payloads


def build_run_config(
    thread_id: str,
    connector: ILLMConnector | None = None,
    registry: ToolRegistry | None = None,
    hitl_manager=None,
    hitl_enabled: bool = True,
    use_interrupt: bool = True,
    sanitizer_force_docker: bool = True,
    user_id: str = "",
) -> dict[str, Any]:
    """构建 ainvoke / Command(resume) 用的 configurable config"""
    return {
        "configurable": {
            "thread_id": thread_id,
            "_user_id": user_id,
            "_connector": connector,
            "_registry": registry,
            "_hitl_manager": hitl_manager,
            "_hitl_enabled": hitl_enabled,
            "_use_interrupt": use_interrupt,
            "_sanitizer_force_docker": sanitizer_force_docker,
        }
    }


# ── 会话上下文 helpers ────────────────────────────────────

def apply_system_prompt(
    messages: list[dict[str, Any]],
    system_prompt: str,
) -> list[dict[str, Any]]:
    """用最新 system prompt（含 RAG）替换旧 system 消息。"""
    rest = [m for m in messages if m.get("role") != "system"]
    if system_prompt:
        return [{"role": "system", "content": system_prompt}, *rest]
    return rest


def trim_conversation_messages(
    messages: list[dict[str, Any]],
    max_non_system: int = MAX_CONTEXT_MESSAGES,
) -> list[dict[str, Any]]:
    """保留 system + 最近若干条非 system 消息，避免上下文撑爆 LLM。"""
    if not messages:
        return messages
    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]
    system = system_msgs[-1:] if system_msgs else []
    if len(non_system) > max_non_system:
        non_system = non_system[-max_non_system:]
    return system + non_system


def _fresh_turn_state(
    messages: list[dict[str, Any]],
    *,
    prior: dict[str, Any] | None = None,
) -> AgentState:
    """新 turn 的初始 state：重置工具轮次，保留 messages。"""
    state: AgentState = {
        "messages": messages,
        "tool_calls": [],
        "tool_results": [],
        "final_response": "",
        "tool_round": 0,
        "attachments": [],
    }
    if prior and prior.get("force_docker_sandbox"):
        state["force_docker_sandbox"] = prior["force_docker_sandbox"]
    return state


# ── 便捷执行函数 ──────────────────────────────────────────

async def run_agent(
    graph,
    user_message: str,
    system_prompt: str = "",
    connector: ILLMConnector | None = None,
    registry: ToolRegistry | None = None,
    history: list[dict[str, Any]] | None = None,
    thread_id: str | None = None,
    user_id: str = "",
    hitl_manager=None,
    hitl_enabled: bool = True,
    sanitizer_force_docker: bool = True,
    continue_thread: bool = False,
) -> AgentState:
    """执行一次 Agent 推理

    Args:
        graph: compiled LangGraph
        user_message: 用户输入
        system_prompt: 系统提示
        connector: LLM 连接器
        registry: 工具注册表
        history: 对话历史（仅 fresh turn 时使用）
        continue_thread: 从 checkpointer 续聊，追加 user 消息
    """
    effective_thread = thread_id or str(__import__("uuid").uuid4())
    use_interrupt = getattr(graph, "_checkpointer", None) is not None
    config = build_run_config(
        thread_id=effective_thread,
        connector=connector or getattr(graph, "_connector", None),
        registry=registry or getattr(graph, "_registry", None),
        hitl_manager=hitl_manager or getattr(graph, "_hitl_manager", None),
        hitl_enabled=hitl_enabled,
        use_interrupt=use_interrupt,
        sanitizer_force_docker=sanitizer_force_docker,
        user_id=user_id,
    )

    initial_state: AgentState | None = None

    if continue_thread and use_interrupt:
        try:
            snap = await graph.aget_state(config)
        except Exception as e:
            logger.warning("[run_agent] 读取 checkpoint 失败 thread=%s: %s", effective_thread, e)
            snap = None
        if snap and snap.values and snap.values.get("messages"):
            messages = apply_system_prompt(list(snap.values["messages"]), system_prompt)
            messages.append({"role": "user", "content": user_message})
            messages = trim_conversation_messages(messages)
            initial_state = _fresh_turn_state(messages, prior=snap.values)

    if initial_state is None:
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        initial_state = _fresh_turn_state(messages)

    return await graph.ainvoke(initial_state, config)


# ── Helpers ───────────────────────────────────────────────

def _error_state(state: AgentState, message: str) -> AgentState:
    return {
        **state,
        "final_response": f"❌ {message}",
        "tool_calls": [],
    }
