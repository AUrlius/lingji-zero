# Custom tool example

This directory shows how to extend the Agent with **in-process tools** (no plugin market, no MCP).

## Files

| File | Purpose |
|------|---------|
| `hello_tool.py` | `register_custom_tools(reg)` — copy pattern into `lingji-agent` |
| Test | `lingji-agent/tests/test_custom_tool_example.py` |

## Wire into a running Agent

1. Copy `hello_tool.py` to e.g. `lingji-agent/src/lingji_agent/execution/tools/custom_tools.py`.
2. In `main.py`, after other tool imports:

```python
from lingji_agent.execution.tools import custom_tools  # noqa: F401 — side effect optional
from lingji_agent.execution.tools.custom_tools import register_custom_tools

register_custom_tools(registry)
```

Alternatively merge `@registry.register` decorators into an existing `*_tools.py` module and keep the `import ... fs_tools` side-effect pattern used today.

## Risk levels

| `RiskLevel` | Behavior |
|-------------|----------|
| `SAFE` | Runs in sandbox as usual |
| `CRITICAL` | HITL approval on phone/Web; sanitizer threats may force Docker |

See [CONTRIBUTING.md](../../CONTRIBUTING.md#adding-a-tool) for the PR checklist.

## Not supported yet

- Dynamic `pip install` plugins
- `lingji.plugin.yaml` / Sidecar (Sprint 13 / 六期)
- MCP servers (see [docs/MCP_INTEGRATION_SPIKE.md](../docs/MCP_INTEGRATION_SPIKE.md))
