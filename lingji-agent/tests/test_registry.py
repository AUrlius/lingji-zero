"""Tool 注册表单元测试"""

import pytest
from lingji_agent.execution.registry import ToolRegistry, RiskLevel


class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()

        @reg.register(
            name="echo",
            description="echo back",
            parameters={"type": "object", "properties": {}},
        )
        async def echo():
            return "ok"

        tool = reg.get("echo")
        assert tool is not None
        assert tool.name == "echo"
        assert tool.risk == RiskLevel.SAFE

    def test_critical_risk(self):
        reg = ToolRegistry()

        @reg.register(
            name="danger",
            description="dangerous",
            parameters={},
            risk=RiskLevel.CRITICAL,
        )
        async def danger():
            pass

        tool = reg.get("danger")
        assert tool.risk == RiskLevel.CRITICAL

    def test_to_openai_schema(self):
        reg = ToolRegistry()

        @reg.register(
            name="test",
            description="test tool",
            parameters={"type": "object", "properties": {"x": {"type": "string"}}},
        )
        async def test():
            pass

        schema = reg.to_openai_schema()
        assert len(schema) == 1
        assert schema[0]["type"] == "function"
        assert schema[0]["function"]["name"] == "test"

    def test_nonexistent_tool(self):
        reg = ToolRegistry()
        assert reg.get("nope") is None
