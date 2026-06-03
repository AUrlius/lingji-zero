"""HITL 集成测试"""

import json
import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from lingji_agent.cognitive.orchestrator import (
    build_graph,
    AgentState,
    build_run_config,
    has_interrupt,
)
from lingji_agent.execution.registry import ToolRegistry, RiskLevel
from lingji_agent.execution.hitl import HITLManager, HITLDecision


@pytest.fixture
def tool_registry():
    reg = ToolRegistry()

    @reg.register(
        name="safe_op",
        description="安全操作",
        parameters={"type": "object", "properties": {}, "required": []},
        risk=RiskLevel.SAFE,
    )
    async def safe_op() -> dict:
        return {"done": True}

    @reg.register(
        name="critical_op",
        description="危险操作",
        parameters={"type": "object", "properties": {}, "required": []},
        risk=RiskLevel.CRITICAL,
    )
    async def critical_op() -> dict:
        return {"done": True}

    return reg


class MockLLM:
    """最小 Mock LLM"""
    def __init__(self):
        self.calls = []
        self.model = "mock"

    @property
    def model_name(self):
        return self.model

    def set_tool_call(self, name: str, args: dict):
        self._next = {
            "content": "",
            "tool_calls": [{
                "id": "call-1",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }],
            "model": self.model,
            "usage": {},
        }

    def set_content(self, text: str):
        self._next = {
            "content": text,
            "tool_calls": [],
            "model": self.model,
            "usage": {},
        }

    async def chat_completion(self, messages, tools=None, stream=False):
        self.calls.append({"messages": messages, "tools": tools})
        return self._next


class TestHITLIntegration:
    @pytest.mark.asyncio
    async def test_safe_tool_executes(self, tool_registry):
        """SAFE 工具直接执行"""
        mock_llm = MockLLM()
        mock_llm.set_tool_call("safe_op", {})

        graph = build_graph(connector=mock_llm, registry=tool_registry)

        state = AgentState(
            messages=[{"role": "user", "content": "do safe"}],
            tool_calls=[], tool_results=[], final_response="", tool_round=0,
        )

        import asyncio
        result = await graph.ainvoke(
            state,
            {"configurable": {"_connector": mock_llm, "_registry": tool_registry, "_hitl_enabled": True}},
        )

        # 验证工具被执行了
        tool_msgs = [m for m in result["messages"] if m.get("role") == "tool"]
        assert len(tool_msgs) > 0
        assert "done" in tool_msgs[0].get("content", "")

    @pytest.mark.asyncio
    async def test_critical_tool_blocked_by_hitl(self, tool_registry):
        """CRITICAL 工具被 HITL 拦截"""
        mock_llm = MockLLM()
        mock_llm.set_tool_call("critical_op", {})

        graph = build_graph(connector=mock_llm, registry=tool_registry)

        state = AgentState(
            messages=[{"role": "user", "content": "do critical"}],
            tool_calls=[], tool_results=[], final_response="", tool_round=0,
        )

        import asyncio
        result = await graph.ainvoke(
            state,
            {"configurable": {"_connector": mock_llm, "_registry": tool_registry, "_hitl_enabled": True}},
        )

        # 验证工具结果中包含 hitl_required
        tool_msgs = [m for m in result["messages"] if m.get("role") == "tool"]
        assert len(tool_msgs) > 0
        content = tool_msgs[0].get("content", "")
        assert "HITL" in content or "hitl_required" in content or "拦截" in content


class TestHITLInterrupt:
    @pytest.mark.asyncio
    async def test_critical_tool_interrupts_graph(self, tool_registry):
        mock_llm = MockLLM()
        mock_llm.set_tool_call("critical_op", {})
        checkpointer = InMemorySaver()
        graph = build_graph(
            connector=mock_llm,
            registry=tool_registry,
            checkpointer=checkpointer,
        )
        thread_id = str(uuid.uuid4())
        state = AgentState(
            messages=[{"role": "user", "content": "do critical"}],
            tool_calls=[],
            tool_results=[],
            final_response="",
            tool_round=0,
        )
        config = build_run_config(
            thread_id=thread_id,
            connector=mock_llm,
            registry=tool_registry,
        )
        result = await graph.ainvoke(state, config)
        assert has_interrupt(result)

    @pytest.mark.asyncio
    async def test_interrupt_resume_approved_executes_tool(self, tool_registry):
        mock_llm = MockLLM()
        mock_llm.set_tool_call("critical_op", {})
        checkpointer = InMemorySaver()
        graph = build_graph(
            connector=mock_llm,
            registry=tool_registry,
            checkpointer=checkpointer,
        )
        thread_id = str(uuid.uuid4())
        state = AgentState(
            messages=[{"role": "user", "content": "do critical"}],
            tool_calls=[],
            tool_results=[],
            final_response="",
            tool_round=0,
        )
        config = build_run_config(
            thread_id=thread_id,
            connector=mock_llm,
            registry=tool_registry,
        )
        result = await graph.ainvoke(state, config)
        assert has_interrupt(result)

        mock_llm.set_content("done")
        resumed = await graph.ainvoke(Command(resume="approved"), config)
        tool_msgs = [m for m in resumed["messages"] if m.get("role") == "tool"]
        assert len(tool_msgs) > 0
        assert "done" in tool_msgs[0].get("content", "")

    @pytest.mark.asyncio
    async def test_interrupt_resume_rejected_skips_tool(self, tool_registry):
        mock_llm = MockLLM()
        mock_llm.set_tool_call("critical_op", {})
        checkpointer = InMemorySaver()
        graph = build_graph(
            connector=mock_llm,
            registry=tool_registry,
            checkpointer=checkpointer,
        )
        thread_id = str(uuid.uuid4())
        state = AgentState(
            messages=[{"role": "user", "content": "do critical"}],
            tool_calls=[],
            tool_results=[],
            final_response="",
            tool_round=0,
        )
        config = build_run_config(
            thread_id=thread_id,
            connector=mock_llm,
            registry=tool_registry,
        )
        await graph.ainvoke(state, config)
        mock_llm.set_content("blocked")
        resumed = await graph.ainvoke(Command(resume="rejected"), config)
        tool_msgs = [m for m in resumed["messages"] if m.get("role") == "tool"]
        assert len(tool_msgs) > 0
        content = tool_msgs[0].get("content", "")
        assert "hitl_rejected" in content or "拒绝" in content
        assert "done" not in content

    @pytest.mark.asyncio
    async def test_interrupt_resume_timeout_skips_tool(self, tool_registry):
        mock_llm = MockLLM()
        mock_llm.set_tool_call("critical_op", {})
        checkpointer = InMemorySaver()
        graph = build_graph(
            connector=mock_llm,
            registry=tool_registry,
            checkpointer=checkpointer,
        )
        thread_id = str(uuid.uuid4())
        state = AgentState(
            messages=[{"role": "user", "content": "do critical"}],
            tool_calls=[],
            tool_results=[],
            final_response="",
            tool_round=0,
        )
        config = build_run_config(
            thread_id=thread_id,
            connector=mock_llm,
            registry=tool_registry,
        )
        await graph.ainvoke(state, config)
        mock_llm.set_content("timed out")
        resumed = await graph.ainvoke(Command(resume="timeout"), config)
        tool_msgs = [m for m in resumed["messages"] if m.get("role") == "tool"]
        assert len(tool_msgs) > 0
        content = tool_msgs[0].get("content", "")
        assert "hitl_rejected" in content or "超时" in content
        assert "done" not in content


    @pytest.mark.asyncio
    async def test_critical_tool_executes_when_hitl_disabled(self, tool_registry):
        """HITL 关闭时，CRITICAL 工具正常执行"""
        mock_llm = MockLLM()
        mock_llm.set_tool_call("critical_op", {})

        graph = build_graph(connector=mock_llm, registry=tool_registry)

        state = AgentState(
            messages=[{"role": "user", "content": "do critical"}],
            tool_calls=[], tool_results=[], final_response="", tool_round=0,
        )

        import asyncio
        result = await graph.ainvoke(
            state,
            {"configurable": {"_connector": mock_llm, "_registry": tool_registry, "_hitl_enabled": False}},
        )

        # 验证工具被执行了（没有被拦截）
        tool_msgs = [m for m in result["messages"] if m.get("role") == "tool"]
        assert len(tool_msgs) > 0
        content = tool_msgs[0].get("content", "")
        assert "done" in content


import asyncio

class TestHITLManagerAsync:
    @pytest.mark.asyncio
    async def test_approve_returns_approved(self):
        mgr = HITLManager(default_timeout=5.0)
        async def delayed_approve():
            await asyncio.sleep(0.1)
            mgr.approve("task-1")
        asyncio.create_task(delayed_approve())
        decision = await mgr.request_approval("task-1", "test op", "critical")
        assert decision == HITLDecision.APPROVED

    @pytest.mark.asyncio
    async def test_timeout_returns_timeout(self):
        mgr = HITLManager(default_timeout=0.3)
        decision = await mgr.request_approval("task-2", "test op", "critical")
        assert decision == HITLDecision.TIMEOUT

    @pytest.mark.asyncio
    async def test_reject_returns_rejected(self):
        mgr = HITLManager(default_timeout=5.0)
        async def delayed_reject():
            await asyncio.sleep(0.1)
            mgr.reject("task-3")
        asyncio.create_task(delayed_reject())
        decision = await mgr.request_approval("task-3", "test op", "warn")
        assert decision == HITLDecision.REJECTED

    def test_pending_count(self):
        mgr = HITLManager(default_timeout=10.0)
        assert mgr.get_pending_count() == 0
