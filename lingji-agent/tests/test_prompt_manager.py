"""Prompt Manager 单元测试"""

import pytest

from lingji_agent.cognitive.prompt_manager import PromptManager, BASE_SYSTEM_PROMPT
from lingji_agent.execution.registry import ToolRegistry, RiskLevel


class TestPromptManager:
    def test_default_prompt(self):
        pm = PromptManager(device_id="test-device")
        prompt = pm.build_system_prompt()
        assert "灵机助手" in prompt
        assert "test-device" in prompt
        assert "Linux" in prompt

    def test_custom_platform(self):
        pm = PromptManager(platform="Windows")
        prompt = pm.build_system_prompt()
        assert "Windows" in prompt

    def test_with_tools(self):
        reg = ToolRegistry()

        @reg.register(
            name="list_dir",
            description="列出目录内容",
            parameters={"type": "object", "properties": {}},
        )
        async def list_dir():
            pass

        pm = PromptManager(registry=reg)
        prompt = pm.build_system_prompt()
        assert "list_dir" in prompt
        assert "列出目录内容" in prompt
        assert "🟢" in prompt  # safe 工具图标

    def test_with_critical_tool(self):
        reg = ToolRegistry()

        @reg.register(
            name="danger_op",
            description="危险操作",
            parameters={},
            risk=RiskLevel.CRITICAL,
        )
        async def danger_op():
            pass

        pm = PromptManager(registry=reg)
        prompt = pm.build_system_prompt()
        assert "🔴" in prompt

    def test_build_messages(self):
        pm = PromptManager(device_id="pc")
        msgs = pm.build_messages("hello world")

        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "hello world"

    def test_build_messages_with_history(self):
        pm = PromptManager()
        history = [
            {"role": "user", "content": "prev question"},
            {"role": "assistant", "content": "prev answer"},
        ]
        msgs = pm.build_messages("new question", history=history)

        assert len(msgs) == 4
        assert msgs[0]["role"] == "system"
        assert msgs[1] == history[0]
        assert msgs[2] == history[1]
        assert msgs[3]["role"] == "user"

    def test_memory_context_injected(self):
        pm = PromptManager(device_id="pc")
        context = "<user_preferences>\n- User Preference: lang is python\n</user_preferences>"
        prompt = pm.build_system_prompt(retrieved_memory_context=context)

        assert "长期记忆" in prompt
        assert "<user_preferences>" in prompt
        assert "lang is python" in prompt

    def test_empty_memory_context_omitted(self):
        pm = PromptManager(device_id="pc")
        prompt = pm.build_system_prompt(retrieved_memory_context="")
        assert "长期记忆" not in prompt

        prompt_whitespace = pm.build_system_prompt(retrieved_memory_context="   ")
        assert "长期记忆" not in prompt_whitespace
