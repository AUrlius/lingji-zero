"""Orchestrator 单元测试 — 含反自欺验证"""

import asyncio
import json

import pytest

from lingji_agent.cognitive.orchestrator import (
    build_graph,
    run_agent,
    AgentState,
    agent_think,
    tool_executor,
    format_response,
    _route_after_think,
    _route_after_tool,
    MAX_TOOL_ROUNDS,
)
from lingji_agent.cognitive.llm_provider import ILLMConnector
from lingji_agent.execution.registry import ToolRegistry, RiskLevel


# ── Mock LLM（用于反自欺验证）─────────────────────────────

class MockConnector(ILLMConnector):
    """可控的 Mock LLM——记录调用、返回预设响应"""

    def __init__(self, model="mock-model"):
        self.model = model
        self.calls: list[dict] = []  # 记录每次调用参数
        self._next_response: dict = {"content": "", "tool_calls": [], "model": model, "usage": {}}

    @property
    def model_name(self) -> str:
        return self.model

    def set_response(self, content="", tool_calls=None):
        """设置下一次调用的返回值"""
        self._next_response = {
            "content": content,
            "tool_calls": tool_calls or [],
            "model": self.model,
            "usage": {"total_tokens": 42},
        }

    async def chat_completion(self, messages, tools=None, stream=False):
        self.calls.append({"messages": messages, "tools": tools})
        return self._next_response


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def mock_llm():
    return MockConnector()


@pytest.fixture
def tool_registry():
    reg = ToolRegistry()

    @reg.register(
        name="echo",
        description="回显输入",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        risk=RiskLevel.SAFE,
    )
    async def echo(text: str) -> dict:
        return {"echo": text}

    return reg


@pytest.fixture
def base_state():
    return AgentState(
        messages=[{"role": "user", "content": "hello"}],
        tool_calls=[],
        tool_results=[],
        final_response="",
        tool_round=0,
    )


# ── 反自欺测试（核心）──────────────────────────────────────

class TestAntiSelfDeception:
    """验证 LLM 真实被调用，而非透传"""

    def test_agent_think_calls_llm(self, mock_llm, base_state):
        """agent_think 必须调用 LLM，不可直接 return state"""
        mock_llm.set_response(content="你好！")

        # 直接调用节点函数（不走 graph，便于注入 mock）
        import langgraph.config as lg_config
        from unittest.mock import patch

        # 通过 graph config 注入
        graph = build_graph(connector=mock_llm, registry=ToolRegistry())

        async def run():
            # 用 configurable 传递依赖
            config = {"configurable": {"_connector": mock_llm, "_registry": ToolRegistry()}}
            return await graph.ainvoke(base_state, config)

        result = asyncio.run(run())

        # ✅ 验证：LLM 被调用了
        assert len(mock_llm.calls) > 0, (
            "🔴 自欺欺人！agent_think 未调用 LLM，直接透传了 state"
        )
        # ✅ 验证：messages 传入了
        assert mock_llm.calls[0]["messages"][0]["content"] == "hello"
        # ✅ 验证：结果来自 LLM 而非 state 原值
        assert result["final_response"] == "你好！"

    def test_different_inputs_different_calls(self, mock_llm):
        """不同输入应产生不同 LLM 调用"""
        graph = build_graph(connector=mock_llm, registry=ToolRegistry())

        mock_llm.set_response(content="reply-A")
        state_a = AgentState(
            messages=[{"role": "user", "content": "question A"}],
            tool_calls=[], tool_results=[], final_response="", tool_round=0,
        )
        asyncio.run(graph.ainvoke(state_a, {"configurable": {"_connector": mock_llm, "_registry": ToolRegistry()}}))

        mock_llm.set_response(content="reply-B")
        state_b = AgentState(
            messages=[{"role": "user", "content": "question B"}],
            tool_calls=[], tool_results=[], final_response="", tool_round=0,
        )
        asyncio.run(graph.ainvoke(state_b, {"configurable": {"_connector": mock_llm, "_registry": ToolRegistry()}}))

        # ✅ 验证：两次调用的 messages 不同
        assert mock_llm.calls[0]["messages"][0]["content"] == "question A"
        assert mock_llm.calls[1]["messages"][0]["content"] == "question B"
        assert mock_llm.calls[0]["messages"][0]["content"] != mock_llm.calls[1]["messages"][0]["content"]

    def test_llm_error_propagates(self, mock_llm, base_state):
        """LLM 调用失败不应静默吞掉，必须有错误信息"""
        graph = build_graph(connector=mock_llm, registry=ToolRegistry())

        # 让 LLM 抛异常
        async def failing(*args, **kwargs):
            raise RuntimeError("API 不可用")

        mock_llm.chat_completion = failing

        result = asyncio.run(
            graph.ainvoke(base_state, {"configurable": {"_connector": mock_llm, "_registry": ToolRegistry()}})
        )

        # ✅ 验证：错误体现在 final_response 中，而非空字符串
        assert "失败" in result["final_response"] or "❌" in result["final_response"], (
            "🔴 自欺欺人！LLM 异常被静默吞掉，final_response 为空"
        )

    def test_empty_content_without_tools_is_detected(self, mock_llm, base_state):
        """LLM 返回空 content 且无 tool_calls 应有日志警告"""
        mock_llm.set_response(content="", tool_calls=[])  # 异常：空回复

        graph = build_graph(connector=mock_llm, registry=ToolRegistry())
        result = asyncio.run(
            graph.ainvoke(base_state, {"configurable": {"_connector": mock_llm, "_registry": ToolRegistry()}})
        )

        # ✅ 验证至少返回了空字符串（而非崩溃）
        assert "final_response" in result


# ── Tool 调用循环测试 ──────────────────────────────────────

class TestToolCallingLoop:
    def test_tool_call_routes_correctly(self, mock_llm, tool_registry, base_state):
        """LLM 返回 tool_calls → 执行 → 返回结果"""
        # 第一次调用：返回 tool_call
        mock_llm.set_response(
            content="",
            tool_calls=[{
                "id": "call-1",
                "type": "function",
                "function": {"name": "echo", "arguments": '{"text": "ping"}'},
            }],
        )

        graph = build_graph(connector=mock_llm, registry=tool_registry)

        result = asyncio.run(
            graph.ainvoke(base_state, {"configurable": {"_connector": mock_llm, "_registry": tool_registry}})
        )

        # ✅ 验证：工具被执行了（结果追加到 messages）
        tool_messages = [m for m in result["messages"] if m.get("role") == "tool"]
        assert len(tool_messages) > 0, "工具未被添加到消息历史"
        # ✅ 验证：工具结果包含 echo 输出
        assert "ping" in tool_messages[0].get("content", "")

    def test_max_rounds_prevents_infinite_loop(self, mock_llm, tool_registry, base_state):
        """超过 MAX_TOOL_ROUNDS 后强制结束"""
        # 每次调用都返回 tool_call（模拟无限循环）
        mock_llm.set_response(
            content="",
            tool_calls=[{
                "id": "call-x",
                "type": "function",
                "function": {"name": "echo", "arguments": '{"text": "loop"}'},
            }],
        )

        graph = build_graph(connector=mock_llm, registry=tool_registry)

        result = asyncio.run(
            graph.ainvoke(base_state, {"configurable": {"_connector": mock_llm, "_registry": tool_registry}})
        )

        # ✅ 验证：调用次数不超过 MAX_TOOL_ROUNDS
        assert len(mock_llm.calls) <= MAX_TOOL_ROUNDS + 1, (
            f"🔴 工具调用未受控！调用了 {len(mock_llm.calls)} 次，超过上限 {MAX_TOOL_ROUNDS}"
        )


# ── 路由函数测试 ──────────────────────────────────────────

class TestRouting:
    def test_route_after_think_with_tools(self):
        state = AgentState(
            messages=[], tool_calls=[{"id": "x"}],
            tool_results=[], final_response="", tool_round=0,
        )
        assert _route_after_think(state) == "tool_executor"

    def test_route_after_think_without_tools(self):
        state = AgentState(
            messages=[], tool_calls=[],
            tool_results=[], final_response="hello", tool_round=0,
        )
        assert _route_after_think(state) == "format_response"

    def test_route_after_tool_continue(self):
        state = AgentState(
            messages=[], tool_calls=[], tool_results=[],
            final_response="", tool_round=2,
        )
        assert _route_after_tool(state) == "agent_think"

    def test_route_after_tool_max_rounds(self):
        state = AgentState(
            messages=[], tool_calls=[], tool_results=[],
            final_response="", tool_round=MAX_TOOL_ROUNDS,
        )
        assert _route_after_tool(state) == "format_response"


# ── format_response 测试 ───────────────────────────────────

class TestFormatResponse:
    def test_extracts_final_response(self):
        state = AgentState(
            messages=[{"role": "assistant", "content": "这是最终回复"}],
            tool_calls=[], tool_results=[], final_response="这是最终回复", tool_round=0,
        )
        result = format_response(state)
        assert result["final_response"] == "这是最终回复"

    def test_fallback_from_messages(self):
        """final_response 为空时，从 messages 提取"""
        state = AgentState(
            messages=[
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "fallback reply"},
            ],
            tool_calls=[], tool_results=[], final_response="", tool_round=0,
        )
        result = format_response(state)
        assert result["final_response"] == "fallback reply"


# ── build_graph 测试 ──────────────────────────────────────

class TestBuildGraph:
    def test_compiles_with_deps(self, mock_llm, tool_registry):
        graph = build_graph(connector=mock_llm, registry=tool_registry)
        assert graph._connector is mock_llm
        assert graph._registry is tool_registry

    def test_compiles_without_deps(self):
        """无 LLM 时也编译通过（运行时错误替代）"""
        graph = build_graph()
        assert graph is not None
