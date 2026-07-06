# Hermes 任务：生产 Gateway 部署 Fleet Phase 3（跨 Agent 文件中继）

> **用法**：交给**有 SSH 权限部署生产 Gateway** 的环境执行（青铜剑 WSL + `deploy-gateway.sh`）。  
> **保存路径建议**：`~/.hermes/tasks/lingji-gateway-fleet3-deploy.md`  
> **前置**：GitHub `main` 已含 `handler/fleet.go` 与 `POST /v1/fleet/transfer`（Phase 3 commit 之后）  
> **生产域名**：`https://lingji.mygoal.tech`

## 任务目标

将生产 Gateway 升级到 **Fleet Phase 3**：

| 项 | 说明 |
|----|------|
| 新能力 | `POST /v1/fleet/transfer`、WS `FLEET_DELIVER` / `FLEET_ACK` |
| 复用 | G6 `/files` 中转；Phase 2 inbox 目录不变 |
| 配套 | 青铜剑 `lingji-pc` + 空城记 `lingji-laptop` **Agent 均需** `git pull` 并重启 |

**不要**修改 `LINGJI_AUTH_TOKEN`（除非用户明确要求轮换）。

## 约束

1. 本任务可 `git pull`，**不要** `git commit/push`（除非用户另嘱）
2. 不要粘贴完整 token / API Key
3. `systemctl restart lingji-gateway` 会有短暂断连
4. SSH 不可用则停止汇报

## 第 0 步：确认本地含 Phase 3

```bash
export REPO=/mnt/e/LingjiPlan/LingjiZero   # 或 ~/lingji-zero
cd "$REPO"
git fetch origin && git pull origin main
test -f lingji-gateway/handler/fleet.go && echo "OK: Phase 3 Gateway"
test -f lingji-agent/src/lingji_agent/execution/tools/fleet_tools.py && echo "OK: Phase 3 Agent"
cd lingji-gateway && go test ./... -count=1
```

## 第 1 步：部署 Gateway

```bash
export LINGJI_SSH_HOST='<向用户确认>'
export LINGJI_SSH_USER="${LINGJI_SSH_USER:-hermes}"
export LINGJI_SSH_KEY="${LINGJI_SSH_KEY:-$HOME/.ssh/lingji_deploy}"
export LINGJI_HEALTH_URL="${LINGJI_HEALTH_URL:-https://lingji.mygoal.tech/health}"

cd "$REPO"
./scripts/deploy-gateway.sh --host "$LINGJI_SSH_HOST" --user "$LINGJI_SSH_USER"
```

Phase 2 已建 `/opt/lingji/data` 则无需重复；见 [gateway-deploy-fleet2-hermes.md](gateway-deploy-fleet2-hermes.md) 第 2 步。

## 第 2 步：验收

```bash
: "${LINGJI_AUTH_TOKEN:?需要 token}"
curl -sf "https://lingji.mygoal.tech/health"
# 404=未部署 Phase 3；400=路由已存在
curl -s -o /dev/null -w "%{http_code}\n" -X POST "https://lingji.mygoal.tech/v1/fleet/transfer" \
  -H "Authorization: Bearer $LINGJI_AUTH_TOKEN" -H "Content-Type: application/json" -d '{}'
```

## 第 3 步：提醒用户（Hermes 不代劳）

| 机器 | 操作 |
|------|------|
| 青铜剑 | `git pull` → `./scripts/restart-agent-wsl.sh` |
| 空城记 | `git pull` → 重启 Agent（`device_id: lingji-laptop`） |

实机：手机选 Laptop →「把文件发到青铜剑」；PC `~/Downloads/LingjiIncoming/` 应出现文件。

## 参考

- [fleet-phase3-transfer.md](fleet-phase3-transfer.md)
- [scripts/deploy-gateway.sh](../../scripts/deploy-gateway.sh)
