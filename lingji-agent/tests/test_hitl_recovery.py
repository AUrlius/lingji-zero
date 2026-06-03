"""GAP-002：崩溃后 HITL 自动 Command(resume) 恢复"""

import json
import uuid
from dataclasses import dataclass

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from lingji_agent.cognitive.orchestrator import (
    AgentState,
    build_graph,
    build_run_config,
    has_interrupt,
)
from lingji_agent.execution.hitl import (
    HITLManager,
    build_recovered_context,
    register_recovered_pending_run,
)
from lingji_agent.foundation.db import (
    get_pending_hitl_session_by_task_id,
    get_pending_hitl_sessions_with_checkpoints,
    init_db,
    save_checkpoint,
)


@dataclass
class PendingRunStub:
    thread_id: str
    device_id: str
    user_text: str
    system_prompt: str
    run_started_at: float = 0.0


class TestBuildRecoveredContext:
    def test_parses_thread_and_messages(self):
        row = {
            "id": "sess-1",
            "checkpoint_id": "ck-1",
            "task_id": "call-1",
            "description": "critical op",
            "risk_level": "critical",
            "thread_id": "phone-a:run-1",
            "agent_state_json": json.dumps(
                {
                    "messages": [
                        {"role": "system", "content": "sys"},
                        {"role": "user", "content": "do critical"},
                    ]
                }
            ),
            "checkpoint_status": "waiting_hitl",
        }
        ctx = build_recovered_context(row, default_device_id="fallback")
        assert ctx.task_id == "call-1"
        assert ctx.thread_id == "phone-a:run-1"
        assert ctx.device_id == "phone-a"
        assert ctx.user_text == "do critical"
        assert ctx.system_prompt == "sys"


class TestPendingHitlJoin:
    def test_join_returns_thread_id(self):
        conn = init_db(":memory:")
        save_checkpoint(
            conn,
            "ck-1",
            "phone:run-1",
            {"messages": [{"role": "user", "content": "hi"}]},
            status="waiting_hitl",
        )
        conn.execute(
            """INSERT INTO hitl_sessions
               (id, checkpoint_id, task_id, description, risk_level)
               VALUES (?, ?, ?, ?, ?)""",
            ("s1", "ck-1", "task-1", "delete file", "critical"),
        )
        conn.commit()
        rows = get_pending_hitl_sessions_with_checkpoints(conn)
        assert len(rows) == 1
        assert rows[0]["thread_id"] == "phone:run-1"
        assert get_pending_hitl_session_by_task_id(conn, "task-1")["task_id"] == "task-1"


class TestCrashRecoveryResume:
    @pytest.fixture
    def tool_registry(self):
        from lingji_agent.execution.registry import ToolRegistry, RiskLevel

        reg = ToolRegistry()

        @reg.register(
            name="critical_op",
            description="danger",
            parameters={"type": "object", "properties": {}, "required": []},
            risk=RiskLevel.CRITICAL,
        )
        async def critical_op() -> dict:
            return {"done": True}

        return reg

    @pytest.mark.asyncio
    async def test_recovered_pending_run_command_resume(self, tool_registry):
        from tests.test_hitl import MockLLM

        conn = init_db(":memory:")
        hitl_mgr = HITLManager(db_conn=conn)
        checkpointer = InMemorySaver()
        mock_llm = MockLLM()
        mock_llm.set_tool_call("critical_op", {})

        graph = build_graph(
            connector=mock_llm,
            registry=tool_registry,
            hitl_manager=hitl_mgr,
            checkpointer=checkpointer,
        )
        thread_id = f"phone-1:{uuid.uuid4()}"
        state = AgentState(
            messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "run critical"},
            ],
            tool_calls=[],
            tool_results=[],
            final_response="",
            tool_round=0,
        )
        config = build_run_config(
            thread_id=thread_id,
            connector=mock_llm,
            registry=tool_registry,
            hitl_manager=hitl_mgr,
        )
        result = await graph.ainvoke(state, config)
        assert has_interrupt(result)

        sessions = get_pending_hitl_sessions_with_checkpoints(conn)
        assert len(sessions) == 1

        pending_runs: dict[str, PendingRunStub] = {}
        register_recovered_pending_run(
            pending_runs,
            sessions[0],
            PendingRunStub,
            default_device_id="phone-1",
        )
        assert "call-1" in pending_runs
        assert pending_runs["call-1"].thread_id == thread_id

        mock_llm.set_content("finished")
        resumed = await graph.ainvoke(Command(resume="approved"), config)
        tool_msgs = [m for m in resumed["messages"] if m.get("role") == "tool"]
        assert len(tool_msgs) > 0
        assert "done" in tool_msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_lazy_load_session_by_task_id(self, tool_registry):
        from tests.test_hitl import MockLLM

        conn = init_db(":memory:")
        hitl_mgr = HITLManager(db_conn=conn)
        checkpointer = InMemorySaver()
        mock_llm = MockLLM()
        mock_llm.set_tool_call("critical_op", {})

        graph = build_graph(
            connector=mock_llm,
            registry=tool_registry,
            hitl_manager=hitl_mgr,
            checkpointer=checkpointer,
        )
        thread_id = f"device-x:{uuid.uuid4()}"
        config = build_run_config(
            thread_id=thread_id,
            connector=mock_llm,
            registry=tool_registry,
            hitl_manager=hitl_mgr,
        )
        await graph.ainvoke(
            AgentState(
                messages=[{"role": "user", "content": "go"}],
                tool_calls=[],
                tool_results=[],
                final_response="",
                tool_round=0,
            ),
            config,
        )

        session = get_pending_hitl_session_by_task_id(conn, "call-1")
        assert session is not None
        ctx = build_recovered_context(session, default_device_id="device-x")
        assert ctx.thread_id == thread_id

        snap = await graph.aget_state(config)
        assert snap.interrupts

        mock_llm.set_content("ok")
        resumed = await graph.ainvoke(Command(resume="approved"), config)
        assert resumed.get("final_response") or any(
            m.get("role") == "tool" for m in resumed["messages"]
        )
