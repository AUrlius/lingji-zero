"""Tests for examples/custom_tool/hello_tool.py (extension pattern)."""

import importlib.util
from pathlib import Path

import pytest

from lingji_agent.execution.registry import ToolRegistry

_EXAMPLE = (
    Path(__file__).resolve().parents[2] / "examples" / "custom_tool" / "hello_tool.py"
)


def _load_example_module():
    spec = importlib.util.spec_from_file_location("hello_tool_example", _EXAMPLE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.asyncio
async def test_hello_custom_tool_example():
    mod = _load_example_module()
    reg = ToolRegistry()
    mod.register_custom_tools(reg)

    tool = reg.get("hello_custom")
    assert tool is not None
    assert tool.risk.value == "safe"

    result = await tool.fn(name="Lingji")
    assert result == {"message": "Hello, Lingji!"}

    schema = reg.to_openai_schema()
    assert any(s["function"]["name"] == "hello_custom" for s in schema)
