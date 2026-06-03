"""G6.1b — 按设备多轮会话（checkpointer 续聊）"""

import asyncio

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from lingji_agent.cognitive.orchestrator import (
    apply_system_prompt,
    build_graph,
    run_agent,
    trim_conversation_messages,
)
from lingji_agent.cognitive.llm_provider import ILLMConnector
from lingji_agent.execution.registry import ToolRegistry


class MockConnector(ILLMConnector):
    def __init__(self, model="mock-model"):
        self.model = model
        self.calls: list[dict] = []
        self._next_response: dict = {
            "content": "",
            "tool_calls": [],
            "model": model,
            "usage": {},
        }

    @property
    def model_name(self) -> str:
        return self.model

    def set_response(self, content="", tool_calls=None):
        self._next_response = {
            "content": content,
            "tool_calls": tool_calls or [],
            "model": self.model,
            "usage": {"total_tokens": 1},
        }

    async def chat_completion(self, messages, tools=None, stream=False):
        self.calls.append({"messages": list(messages), "tools": tools})
        return self._next_response


@pytest.fixture
def mock_llm():
    return MockConnector()


class TestConversationHelpers:
    def test_apply_system_prompt_replaces_old(self):
        msgs = [
            {"role": "system", "content": "old"},
            {"role": "user", "content": "hi"},
        ]
        out = apply_system_prompt(msgs, "new system")
        assert out[0]["content"] == "new system"
        assert out[1]["content"] == "hi"

    def test_trim_keeps_system_and_recent(self):
        msgs = [{"role": "system", "content": "sys"}]
        msgs.extend({"role": "user", "content": str(i)} for i in range(50))
        trimmed = trim_conversation_messages(msgs, max_non_system=10)
        assert trimmed[0]["role"] == "system"
        assert len([m for m in trimmed if m["role"] != "system"]) == 10
        assert trimmed[-1]["content"] == "49"


class TestMultiTurnSession:
    @pytest.mark.asyncio
    async def test_continue_thread_includes_prior_turn(self, mock_llm):
        checkpointer = InMemorySaver()
        graph = build_graph(
            connector=mock_llm,
            registry=ToolRegistry(),
            checkpointer=checkpointer,
        )
        thread_id = "phone-test:session-1"

        mock_llm.set_response(content="你好，小明")
        await run_agent(
            graph=graph,
            user_message="我叫小明",
            system_prompt="你是助手",
            connector=mock_llm,
            registry=ToolRegistry(),
            thread_id=thread_id,
            continue_thread=False,
        )

        mock_llm.set_response(content="你叫小明")
        await run_agent(
            graph=graph,
            user_message="我叫什么？",
            system_prompt="你是助手",
            connector=mock_llm,
            registry=ToolRegistry(),
            thread_id=thread_id,
            continue_thread=True,
        )

        assert len(mock_llm.calls) == 2
        second_msgs = mock_llm.calls[1]["messages"]
        roles = [m["role"] for m in second_msgs]
        assert "user" in roles
        assert roles.count("user") >= 2
        assert any(m.get("content") == "我叫小明" for m in second_msgs)
        assert second_msgs[-1]["content"] == "我叫什么？"

    @pytest.mark.asyncio
    async def test_new_thread_does_not_include_prior(self, mock_llm):
        checkpointer = InMemorySaver()
        graph = build_graph(
            connector=mock_llm,
            registry=ToolRegistry(),
            checkpointer=checkpointer,
        )

        mock_llm.set_response(content="reply-1")
        await run_agent(
            graph=graph,
            user_message="first",
            system_prompt="sys",
            connector=mock_llm,
            registry=ToolRegistry(),
            thread_id="device-a:old",
            continue_thread=False,
        )

        mock_llm.set_response(content="reply-2")
        await run_agent(
            graph=graph,
            user_message="second",
            system_prompt="sys",
            connector=mock_llm,
            registry=ToolRegistry(),
            thread_id="device-a:new",
            continue_thread=False,
        )

        second_msgs = mock_llm.calls[1]["messages"]
        assert len([m for m in second_msgs if m.get("role") == "user"]) == 1
        assert second_msgs[-1]["content"] == "second"


class TestEpisodicThreadScope:
    def test_new_session_excludes_prior_episodic(self):
        from lingji_agent.foundation.config import MemoryConfig
        from lingji_agent.memory.manager import MemoryManager

        class FakeStore:
            def __init__(self):
                self.searches: list[dict] = []

            def search(self, collection_name, query, top_k=3, *, metadata_filter=None):
                self.searches.append({
                    "collection": collection_name,
                    "query": query,
                    "metadata_filter": metadata_filter,
                })
                if collection_name == "episodic" and metadata_filter:
                    tid = metadata_filter.get("thread_id")
                    if tid == "phone:new":
                        return []
                    if tid == "phone:old":
                        return [{
                            "content": "[USER]: 我叫小明",
                            "metadata": {"thread_id": "phone:old"},
                            "relevance_score": 0.9,
                        }]
                if collection_name == "semantic":
                    return []
                return []

        store = FakeStore()
        mgr = MemoryManager(MemoryConfig(enabled=True), vector_store=store)
        mgr._ready = True

        ctx_old = mgr.retrieve_context("我叫什么", episodic_thread_id="phone:old")
        assert "小明" in ctx_old

        ctx_new = mgr.retrieve_context("我叫什么", episodic_thread_id="phone:new")
        assert "小明" not in ctx_new
        assert store.searches[-1]["metadata_filter"] == {"thread_id": "phone:new"}
