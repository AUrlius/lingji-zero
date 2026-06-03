"""会话历史提取 — Web UI history API"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from lingji_agent.cognitive.orchestrator import build_graph, run_agent
from lingji_agent.cognitive.session_history import extract_ui_history, load_thread_ui_history
from lingji_agent.cognitive.llm_provider import ILLMConnector
from lingji_agent.execution.registry import ToolRegistry


class MockConnector(ILLMConnector):
    def __init__(self, model="mock-model"):
        self.model = model
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
        return self._next_response


class TestExtractUiHistory:
    def test_skips_system_and_tool(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "嗨"},
            {"role": "tool", "tool_call_id": "1", "content": "{}"},
        ]
        out = extract_ui_history(msgs)
        assert out == [
            {"role": "user", "text": "你好"},
            {"role": "agent", "text": "嗨"},
        ]

    def test_skips_empty_assistant_with_tool_calls_only(self):
        msgs = [
            {"role": "user", "content": "run"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        ]
        out = extract_ui_history(msgs)
        assert out == [{"role": "user", "text": "run"}]

    def test_trims_to_limit(self):
        msgs = [{"role": "user", "content": str(i)} for i in range(60)]
        out = extract_ui_history(msgs, limit=10)
        assert len(out) == 10
        assert out[0]["text"] == "50"
        assert out[-1]["text"] == "59"


@pytest.mark.asyncio
async def test_load_thread_ui_history_from_checkpoint():
    mock_llm = MockConnector()
    checkpointer = InMemorySaver()
    graph = build_graph(
        connector=mock_llm,
        registry=ToolRegistry(),
        checkpointer=checkpointer,
    )
    thread_id = "phone-test:hist-1"

    mock_llm.set_response(content="回复一")
    await run_agent(
        graph=graph,
        user_message="问题一",
        system_prompt="你是助手",
        connector=mock_llm,
        registry=ToolRegistry(),
        thread_id=thread_id,
        continue_thread=False,
    )

    mock_llm.set_response(content="回复二")
    await run_agent(
        graph=graph,
        user_message="问题二",
        system_prompt="你是助手",
        connector=mock_llm,
        registry=ToolRegistry(),
        thread_id=thread_id,
        continue_thread=True,
    )

    history = await load_thread_ui_history(graph, thread_id, connector=mock_llm)
    assert history == [
        {"role": "user", "text": "问题一"},
        {"role": "agent", "text": "回复一"},
        {"role": "user", "text": "问题二"},
        {"role": "agent", "text": "回复二"},
    ]
