"""Tool 注册表 — @register 装饰器 + 自动生成 Function Calling JSON Schema"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class RiskLevel(str, Enum):
    SAFE = "safe"
    WARN = "warn"
    CRITICAL = "critical"


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict[str, Any]
    risk: RiskLevel
    fn: Callable


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDef] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        risk: RiskLevel = RiskLevel.SAFE,
    ):
        def decorator(fn: Callable):
            self._tools[name] = ToolDef(
                name=name,
                description=description,
                parameters=parameters,
                risk=risk,
                fn=fn,
            )
            return fn
        return decorator

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def list_all(self) -> list[ToolDef]:
        return list(self._tools.values())

    def to_openai_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]


# 全局实例
registry = ToolRegistry()
