# LingjiZero Scripts

运维与 CI 脚本。**公开仓库中不得硬编码生产主机、密钥或个人路径**；一律通过环境变量注入。

## 生产部署（私有运维）

| 脚本 | 用途 | 必需环境变量 |
|------|------|--------------|
| `deploy-gateway.sh` | 构建并 SSH 部署 Gateway | `LINGJI_SSH_HOST`；可选 `LINGJI_SSH_USER`、`LINGJI_SSH_KEY`、`LINGJI_GATEWAY_PATH`、`LINGJI_HEALTH_URL` |
| `restart-agent-wsl.sh` | WSL 重启 Agent | 无（本地路径 `/mnt/e/LingjiPlan/LingjiZero`） |

示例（勿提交真实主机到公开 fork）：

```bash
export LINGJI_SSH_HOST=your.gateway.host
export LINGJI_HEALTH_URL=https://your.gateway.host/health
./scripts/deploy-gateway.sh
```

## 测试 / 冒烟

| 脚本 | 用途 |
|------|------|
| `prod-e2e-smoke.py` | 生产路径 WS 冒烟（默认 `lingji.mygoal.tech` 可通过 `--host` 覆盖） |
| `compose-integration-smoke.sh` | 本地 compose 6/6 |
| `ci-integration.sh` | GHA 集成 job 入口 |
| `gateway_burst.py` | 压力抽检 |
| `chaos-spotcheck.sh` | 混沌抽检 |

`prod-e2e-smoke.py` 读取 `LINGJI_AUTH_TOKEN` 或 `lingji-agent/config/default_config.yaml`（本地，已 gitignore）。

## 开源审计结论（2026-06-03）

- `deploy-gateway.sh`：无默认生产 IP；health 默认 `http://127.0.0.1:8765/health`
- `prod-e2e-smoke.py`：默认 host 为示例域名，部署前请 `--host` / env
- 无脚本内含 API Key 或 auth token

详见 [专利申报与开源前置清单](../../docs/ip/2026-06-03-专利申报与开源前置清单.md)（LingjiPlan 私有文档，不随 LingjiZero 公开）。
