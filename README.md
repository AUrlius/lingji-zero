# LingjiZero

**Control your PC from your phone — with human approval before dangerous tools run.**

Local-first remote agent: LangGraph on your machine, Go Gateway for devices, sandboxed tools, and file push to mobile/web.

[中文说明](README_zh.md)

[![CI](https://github.com/AUrlius/lingji-zero/actions/workflows/ci.yml/badge.svg)](https://github.com/AUrlius/lingji-zero/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/tag/AUrlius/lingji-zero?label=release)](https://github.com/AUrlius/lingji-zero/releases/tag/v0.1.0-mvp)

---

## Why not another chat box?

Most “AI agents” stop at a chat window. LingjiZero is built for **doing work on your PC** from a phone or browser — safely.

| Pain | LingjiZero |
|------|------------|
| Agent runs shell/delete on your machine with no gate | **HITL:** CRITICAL tools pause until you approve on phone/web |
| One-size sandbox for everything | **Risk levels + sanitizer:** suspicious input can force Docker isolation |
| Hard to get files off the PC | **G6:** push files from PC to the chat for download |
| Opaque monolith | **Open stack:** Python Agent + Go Gateway + embed web shell — fork and extend |

---

## What you get (today)

| Implemented | Not in this release |
|-------------|---------------------|
| Phone/Web → Gateway → LangGraph Agent | Plugin marketplace |
| 9 built-in tools (files, shell, system, push-to-user) | MCP client (design only) |
| HITL approve/reject + crash recovery | VLM / GUI automation |
| Native + Docker sandbox, FailClosed | microVM |
| Prompt sanitizer + guardrails | `lingji init` CLI |
| Docker Compose local stack, **248** unit tests + CI | |

Extend via PR: [examples/custom_tool/](examples/custom_tool/) · [CONTRIBUTING.md](CONTRIBUTING.md#adding-a-tool)

---

## Architecture

```
  Phone / Web                Gateway (Go)              Agent (Python)
  lingji-phone/         lingji-gateway:8765      lingji-agent/
  embed web shell  ──WS──▶  auth + routing  ◀──WS──  LangGraph
       │                         │                      │
       │                    HTTP /files                  ├── LLM (OpenAI-compatible)
       │                    (attachments)               ├── 9 tools + sandbox
       └──── HITL_REQ / AGENT_RES ────────────────────────┘
```

Production Gateway is **Go** (`lingji-gateway/`); `lingji-gateway-node/` is an experimental Node.js spike. GitHub language stats count both it and `lingji-gateway/web/js/` as **JavaScript** (not a separate Node.js label).

---

## Quick start (~5 minutes)

Requires **Docker**, **Python 3.11+**, and **Go 1.22+** (for smoke script building Gateway).

```bash
git clone https://github.com/AUrlius/lingji-zero.git
cd lingji-zero
cp .env.example .env          # optional: DEEPSEEK_API_KEY, LINGJI_AUTH_TOKEN
./scripts/setup-compose.sh
docker compose up -d gateway
./scripts/compose-integration-smoke.sh   # expect 6/6
```

Then configure the Agent (see **Developer setup** below), point it at your Gateway, and open the embedded web UI or run `lingji-phone/phone_client.py`.

---

## Extend

1. Read [examples/custom_tool/README.md](examples/custom_tool/README.md)
2. Register tools with `@registry.register` and `RiskLevel`
3. Import from `main.py` · add tests

Future bridge (not implemented): [docs/MCP_INTEGRATION_SPIKE.md](docs/MCP_INTEGRATION_SPIKE.md)

<details>
<summary><strong>Developer setup</strong> (Agent + Gateway from source)</summary>

### Agent

```bash
cd lingji-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp config/default_config.yaml.example config/default_config.yaml
# Edit: llm.api_key, network.auth_token, network.gateway_host

python -m pytest tests/ -q
```

### Gateway

```bash
cd lingji-gateway
go test ./...
go build -o lingji-gateway .
```

### Integration (local Gateway binary)

```bash
cd lingji-agent
python tests/integration_test.py
```

### Phone CLI

```bash
cd lingji-phone
python phone_client.py
```

WSL path notes: [MIGRATION.md](MIGRATION.md)

</details>

---

## Docs

- [MIGRATION.md](MIGRATION.md) — layout, WSL paths
- [CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md)

## License

Copyright 2026 Lingji Project Contributors. [Apache License 2.0](LICENSE).
