# Open Source Release Checklist

Use when publishing the **LingjiZero** public mirror (`lingji-zero`).

**Decision (2026-06-03):** No patent filings. Publish source under Apache-2.0.

Private LingjiPlan docs (`docs/ip/`, internal runbooks) are **not** included in the public tree.

## Pre-flight

- [x] Decided not to file patents
- [x] Disclosure materials R1–R5 archived privately (optional reference only)
- [ ] Secret scan clean (see below)
- [ ] `default_config.yaml` not tracked; `.env` not tracked
- [ ] Review `scripts/` for hardcoded hosts ([scripts/README.md](scripts/README.md))

### Secret scan

```bash
# From LingjiZero root — should return no real keys in tracked files
git ls-files | grep -v node_modules | grep -v .venv | xargs grep -E 'sk-[a-zA-Z0-9]{20,}' || true
git log --all -- lingji-agent/config/default_config.yaml   # should be empty if never committed
```

If `default_config.yaml` ever entered git history, **rotate API keys** before pushing.

## Repository setup

- [ ] Create **public** repo `USERNAME/lingji-zero`
- [ ] Push **this directory only** (not full LingjiPlan)
- [ ] Include: `LICENSE`, `NOTICE`, `README.md`, `CONTRIBUTING.md`, `SECURITY.md`
- [ ] Exclude: `.venv`, `default_config.yaml`, `docs/ip/` (not in tree)

## README requirements

- [ ] Quick Start: compose smoke 6/6 or integration script
- [ ] Architecture diagram (Phone → Gateway → Agent)
- [ ] **Scope** section (9 tools, G6, HITL, sandbox)
- [ ] Link [examples/custom_tool/](examples/custom_tool/) and [CONTRIBUTING.md](CONTRIBUTING.md#adding-a-tool)
- [ ] No **Patent Notice** (not filing)
- [ ] No claims for unimplemented features (see **Forbidden claims**)

### Forbidden claims

| Do not advertise | Say instead |
|------------------|-------------|
| Plugin marketplace | "Add tools via PR; see CONTRIBUTING" |
| MCP integration live | "Design: docs/MCP_INTEGRATION_SPIKE.md" |
| VLM / microVM / Firecracker | Not in MVP |
| Pending patent applications | Removed — not filing |

## CI (v0.1)

- [ ] `.github/workflows/ci.yml` — pytest + go test on push

## Post-release

- [ ] Tag `v0.1.0-mvp`
- [ ] Update private LingjiPlan `AGENTS.md` + `docs/ip/2026-06-03-专利申报与开源前置清单.md` with repo URL
