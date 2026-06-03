# LingjiZero

**用手机遥控你电脑上的 Agent — 危险操作先等你点批准。**

本地优先的远程 PC Agent：LangGraph 跑在本机，Go Gateway 连接手机/浏览器，工具进沙箱，文件可从 PC 推到移动端下载。

[English README](README.md)

[![CI](https://github.com/AUrlius/lingji-zero/actions/workflows/ci.yml/badge.svg)](https://github.com/AUrlius/lingji-zero/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/tag/AUrlius/lingji-zero?label=release)](https://github.com/AUrlius/lingji-zero/releases/tag/v0.1.0-mvp)

---

## 为什么不是又一个聊天框？

很多「AI Agent」停在网页对话框里。灵机面向 **在 PC 上真正执行任务** — 从手机或浏览器发起，并且 **可控、可审计**。

| 痛点 | LingjiZero |
|------|------------|
| Agent 在你电脑上跑 shell/删文件，没有闸门 | **HITL：** CRITICAL 工具挂起，手机/Web 上批准才执行 |
| 沙箱一刀切 | **风险分级 + 清洗：** 可疑输入可强制 Docker 隔离 |
| 文件难从 PC 拿出来 | **G6：** PC 文件推到聊天里下载 |
| 黑盒单体 | **开源栈：** Python Agent + Go Gateway + Web 壳，可 fork 扩展 |

---

## 当前有什么

| 已实现 | 本版本暂无 |
|--------|------------|
| 手机/Web → Gateway → LangGraph Agent | 插件市场 |
| 9 个内置工具（文件、shell、系统、推送给用户） | MCP 客户端（仅有设计文档） |
| HITL 批准/拒绝 + 崩溃续跑 | VLM / GUI 自动化 |
| Native + Docker 沙箱，FailClosed | microVM |
| 对抗性清洗 + Guardrails | `lingji init` CLI |
| Docker Compose 本地栈，**248** 单元测试 + CI | |

扩展方式：PR 加工具 — [examples/custom_tool/](examples/custom_tool/) · [CONTRIBUTING.md](CONTRIBUTING.md#adding-a-tool)

---

## 架构

```
  Phone / Web                Gateway (Go)              Agent (Python)
  lingji-phone/         lingji-gateway:8765      lingji-agent/
  embed web shell  ──WS──▶  auth + routing  ◀──WS──  LangGraph
       │                         │                      │
       │                    HTTP /files                  ├── LLM（OpenAI 兼容）
       │                    （附件下载）                 ├── 9 工具 + 沙箱
       └──── HITL_REQ / AGENT_RES ────────────────────────┘
```

生产 Gateway 为 **Go**（`lingji-gateway/`）；`lingji-gateway-node/` 为 Node.js 实验 Spike。GitHub 语言统计将其与 `lingji-gateway/web/js/` 一并计入 **JavaScript**，不会单独显示 Node.js。

---

## 快速开始（约 5 分钟）

需要 **Docker**、**Python 3.11+**、**Go 1.22+**（冒烟脚本会编译 Gateway）。

```bash
git clone https://github.com/AUrlius/lingji-zero.git
cd lingji-zero
cp .env.example .env          # 可选：DEEPSEEK_API_KEY、LINGJI_AUTH_TOKEN
./scripts/setup-compose.sh
docker compose up -d gateway
./scripts/compose-integration-smoke.sh   # 期望 6/6
```

然后按下方 **开发者安装** 配置 Agent，连上 Gateway，打开 Web 壳或运行 `lingji-phone/phone_client.py`。

---

## 扩展

1. 阅读 [examples/custom_tool/README.md](examples/custom_tool/README.md)
2. 用 `@registry.register` 注册工具并设置 `RiskLevel`
3. 在 `main.py` 中 import · 补测试

后续可能方向（未实现）：[docs/MCP_INTEGRATION_SPIKE.md](docs/MCP_INTEGRATION_SPIKE.md)

<details>
<summary><strong>开发者安装</strong>（从源码跑 Agent + Gateway）</summary>

### Agent

```bash
cd lingji-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp config/default_config.yaml.example config/default_config.yaml
# 编辑：llm.api_key、network.auth_token、network.gateway_host

python -m pytest tests/ -q
```

### Gateway

```bash
cd lingji-gateway
go test ./...
go build -o lingji-gateway .
```

### 集成测试（本机 Gateway）

```bash
cd lingji-agent
python tests/integration_test.py
```

### Phone CLI

```bash
cd lingji-phone
python phone_client.py
```

WSL 路径说明：[MIGRATION.md](MIGRATION.md)

</details>

---

## 文档

- [MIGRATION.md](MIGRATION.md) — 目录与 WSL 路径
- [CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md)

## 许可证

Copyright 2026 Lingji Project Contributors. [Apache License 2.0](LICENSE).
