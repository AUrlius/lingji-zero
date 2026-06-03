# Contributing to LingjiZero

Thank you for your interest in contributing. This repository is the **source code monorepo** for the Lingji agent stack (Python Agent, Go Gateway, Phone simulator).

## Before you start

1. Read [README.md](README.md) for architecture, **scope**, and quick start.
2. Do **not** commit secrets: copy `lingji-agent/config/default_config.yaml.example` to `default_config.yaml` locally (gitignored).

## Development setup

```bash
# Agent (WSL recommended)
cd lingji-agent && python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp config/default_config.yaml.example config/default_config.yaml
python -m pytest tests/ -q

# Gateway
cd lingji-gateway && go test ./...
```

## Adding a tool

Extensions today are **in-process**: new Python modules registered on `ToolRegistry`. There is no plugin marketplace or dynamic `pip install` yet.

1. **Study the example:** [examples/custom_tool/](examples/custom_tool/)
2. **Implement:** use `@registry.register(name=..., description=..., parameters=..., risk=...)` on an `async def` handler.
3. **Wire:** import your module from `lingji-agent/src/lingji_agent/main.py` (same pattern as `fs_tools`, `sys_tools`, `file_tools`).
4. **Test:** add `lingji-agent/tests/test_*.py`; run `python -m pytest tests/ -q`.

### Tool PR checklist

- [ ] Tool name is unique; JSON Schema `parameters` matches function kwargs
- [ ] `RiskLevel.CRITICAL` only for destructive or shell-level actions; document why
- [ ] Paths use `validate_path` / sandbox where touching filesystem (see `fs_tools.py`)
- [ ] No secrets, fixed production hosts, or credentials in code
- [ ] Unit test covers happy path; CRITICAL tools note HITL in description
- [ ] README / user docs updated only if user-visible behavior changes
- [ ] PR does **not** claim plugin market, MCP, VLM, or microVM unless actually implemented

### Risk levels

| Level | When to use | Runtime |
|-------|-------------|---------|
| `SAFE` | Read-only or low-impact | Sandbox + normal execution |
| `WARN` | Reserved for future policy | — |
| `CRITICAL` | Delete, shell, sensitive writes | HITL on phone/Web; sanitizer may force Docker |

External integrations (MCP): design only — [docs/MCP_INTEGRATION_SPIKE.md](docs/MCP_INTEGRATION_SPIKE.md).

## Pull request guidelines

- One logical change per PR; match existing code style.
- Run `pytest tests/` (agent) and `go test ./...` (gateway) before submitting.
- Update tests when changing behavior; avoid drive-by refactors.
- Do not expand scope into unimplemented roadmap items (VLM, plugin market, microVM).

## Code of conduct

Be respectful and constructive. Security issues: see [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).
