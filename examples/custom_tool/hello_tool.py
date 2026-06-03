"""Example: register a custom tool on a ToolRegistry.

Copy this pattern into ``lingji-agent/src/lingji_agent/execution/tools/``
and import the module from ``main.py`` (see examples/custom_tool/README.md).
"""

from __future__ import annotations

from lingji_agent.execution.registry import RiskLevel, ToolRegistry


def register_custom_tools(reg: ToolRegistry) -> None:
    """Register example tools on *reg* (use isolated registry in tests)."""

    @reg.register(
        name="hello_custom",
        description="Return a greeting (example extension tool)",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name to greet"},
            },
            "required": ["name"],
        },
        risk=RiskLevel.SAFE,
    )
    async def hello_custom(name: str) -> dict[str, str]:
        return {"message": f"Hello, {name}!"}
