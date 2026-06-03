# LingjiZero

Local-first **remote PC Agent**: control a LangGraph agent on your machine from a phone or web chat shell, with HITL approval and sandboxed tools.

**License:** [Apache-2.0](LICENSE) · **Repository:** https://github.com/AUrlius/lingji-zero

## Architecture

```
  Phone / Web                Gateway (Go)              Agent (Python)
  lingji-phone/         lingji-gateway:8765      lingji-agent/
  embed web shell  ──WS──▶  auth + routing  ◀──WS──  LangGraph
       │                         │                      │
       │                    HTTP /files                  ├── LLM (DeepSeek)
       │                    (G6 attachments)              ├── 9 tools + sandbox
       └──── HITL_REQ / AGENT_RES ────────────────────────┘
```

## Structure

```
LingjiZero/
├── lingji-agent/         # Python Agent Client
├── lingji-gateway/       # Go Gateway (production)
├── lingji-gateway-node/  # Node spike (8766, non-production)
├── lingji-phone/         # CLI + Web simulator
├── examples/custom_tool/ # How to add tools
├── docs/                 # Technical notes (e.g. MCP spike design)
└── README.md
```

**Scope (today):** Phone/Web → Gateway → LangGraph + **9 built-in tools**, HITL, sanitizer/sandbox, G6 file push/download.

**Not in this release:** plugin marketplace, MCP client, VLM, microVM. See [CONTRIBUTING.md](CONTRIBUTING.md#adding-a-tool) to add tools via PR.

## Quick start (WSL Ubuntu-24.04)

Example path: `/mnt/e/LingjiPlan/LingjiZero` (Windows: `E:\LingjiPlan\LingjiZero`).

### Agent

```bash
cd lingji-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp config/default_config.yaml.example config/default_config.yaml
# Edit default_config.yaml: DEEPSEEK_API_KEY or llm.api_key, network.auth_token

python -m pytest tests/ -q
```

### Gateway

```bash
cd lingji-gateway
go test ./...
go build -o lingji-gateway .
```

### Integration

**Docker compose (recommended)**

```bash
cd ..   # LingjiZero root
cp .env.example .env   # optional secrets
./scripts/setup-compose.sh
docker compose up -d gateway
./scripts/compose-integration-smoke.sh   # expect 6/6
```

**Local Gateway binary**

```bash
cd lingji-agent
python tests/integration_test.py
```

### Phone

```bash
cd lingji-phone
python phone_client.py   # requires Gateway + Agent online
```

## Extending the Agent (tools)

1. Read [examples/custom_tool/README.md](examples/custom_tool/README.md)
2. Register with `@registry.register` and set `RiskLevel`
3. Import your module from `main.py` at startup
4. Add tests (see `lingji-agent/tests/test_custom_tool_example.py`)

Future: [docs/MCP_INTEGRATION_SPIKE.md](docs/MCP_INTEGRATION_SPIKE.md) (design only).

## Docs

- [MIGRATION.md](MIGRATION.md) — layout and WSL paths
- [CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md)
- [OPEN_SOURCE_RELEASE.md](OPEN_SOURCE_RELEASE.md) — release checklist

## License

Copyright 2026 Lingji Project Contributors. Licensed under the Apache License, Version 2.0.
