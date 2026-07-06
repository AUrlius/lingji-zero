# Hermes 任务：生产 Gateway 部署 Fleet Phase 2（inbox + Web v0.1.5）

> **用法**：交给**有 SSH 权限部署生产 Gateway** 的环境执行（青铜剑 WSL + `deploy-gateway.sh`，或 VPS 上 Hermes）。  
> **保存路径建议**：`~/.hermes/tasks/lingji-gateway-fleet2-deploy.md`  
> **目标 commit**：`d81ad20` 或更新 — `feat(fleet): Gateway inbox Phase 2 and Web v0.1.5`  
> **生产域名**：`https://lingji.mygoal.tech`

## 任务目标

将生产 Gateway 升级到 **Fleet Phase 2**：

| 项 | 说明 |
|----|------|
| 新能力 | SQLite inbox、`GET /v1/inbox/threads`、`GET /v1/inbox/messages` |
| Web | 内嵌静态资源 **v0.1.5**（跨 Agent 侧栏 + Laptop/PC 标签） |
| 依赖 | 工作目录下可写 `data/inbox.db`（或 `LINGJI_INBOX_DB`） |
| 配套 | 青铜剑 + 空城记 **Agent 也需** `git pull` 并重启（另见笔记本验收文档） |

**不要**在本任务中修改 `LINGJI_AUTH_TOKEN`（除非用户明确要求轮换）。

## 重要约束

1. **不要 git commit/push**（代码应已在 GitHub `main`；本任务只部署二进制）
2. **不要**在汇报中粘贴完整 token / API Key
3. 部署脚本会 `sudo systemctl restart lingji-gateway`，确认用户接受短暂断连
4. 若 SSH / 密钥不可用，**停止并汇报**，不要猜 IP 或密码

## 第 0 步：确认本地仓库版本

在**用于构建的 WSL**（默认青铜剑 `/mnt/e/LingjiPlan/LingjiZero` 或 `~/lingji-zero`）：

```bash
export REPO=/mnt/e/LingjiPlan/LingjiZero   # 按实际修改
cd "$REPO"
git fetch origin
git log -1 --oneline
git merge-base --is-ancestor d81ad20 HEAD && echo "OK: >= Fleet Phase 2" || echo "FAIL: 需要 git pull"
```

若落后：

```bash
cd "$REPO" && git pull origin main
```

快速确认 Phase 2 文件存在：

```bash
test -f lingji-gateway/store/inbox.go && grep -q '0.1.5' lingji-gateway/web/index.html && echo "OK: Phase 2 tree"
```

## 第 1 步：准备 SSH 与构建环境

向用户确认或读取环境变量：

| 变量 | 典型值 | 用途 |
|------|--------|------|
| `LINGJI_SSH_HOST` | 生产 VPS IP/主机名 | `deploy-gateway.sh` 目标 |
| `LINGJI_SSH_USER` | `hermes` | SSH 用户 |
| `LINGJI_SSH_KEY` | `~/.ssh/lingji_deploy` | 私钥路径（若用密钥登录） |
| `LINGJI_GATEWAY_PATH` | `/opt/lingji/lingji-gateway` | 远端二进制路径 |
| `LINGJI_HEALTH_URL` | `https://lingji.mygoal.tech/health` | 公网验收（可选） |

```bash
export LINGJI_SSH_HOST='向用户索取或已 export'
export LINGJI_SSH_USER="${LINGJI_SSH_USER:-hermes}"
# export LINGJI_SSH_KEY=~/.ssh/lingji_deploy
export LINGJI_HEALTH_URL="${LINGJI_HEALTH_URL:-https://lingji.mygoal.tech/health}"
```

测试 SSH（不执行部署）：

```bash
ssh ${LINGJI_SSH_KEY:+-i "$LINGJI_SSH_KEY"} -o ConnectTimeout=10 \
  "${LINGJI_SSH_USER}@${LINGJI_SSH_HOST}" 'whoami && hostname'
```

## 第 2 步：远端准备 inbox 数据目录

Gateway systemd 工作目录一般为 **`/opt/lingji`**（见 `.gaps/phase-08.md`）。  
Phase 2 默认数据库：`data/inbox.db` → **`/opt/lingji/data/inbox.db`**。

在 VPS 上执行（可由 `ssh` 一次性完成）：

```bash
ssh ${LINGJI_SSH_KEY:+-i "$LINGJI_SSH_KEY"} "${LINGJI_SSH_USER}@${LINGJI_SSH_HOST}" bash -s <<'REMOTE'
set -euo pipefail
sudo mkdir -p /opt/lingji/data
sudo chown hermes:hermes /opt/lingji/data
# 可选：显式指定 DB 路径（写入 env 文件，若已有 /opt/lingji/env 则合并）
if [[ -f /opt/lingji/env ]]; then
  if ! grep -q '^LINGJI_INBOX_DB=' /opt/lingji/env 2>/dev/null; then
    echo 'LINGJI_INBOX_DB=/opt/lingji/data/inbox.db' | sudo tee -a /opt/lingji/env >/dev/null
  fi
else
  echo 'LINGJI_INBOX_DB=/opt/lingji/data/inbox.db' | sudo tee /opt/lingji/env >/dev/null
fi
# 确保 systemd 加载 env（若 unit 已有 EnvironmentFile=-/opt/lingji/env 可跳过）
grep -q 'EnvironmentFile' /etc/systemd/system/lingji-gateway.service 2>/dev/null || \
  echo "注意: 请确认 lingji-gateway.service 含 EnvironmentFile=-/opt/lingji/env 或 WorkingDirectory=/opt/lingji"
ls -la /opt/lingji/data
REMOTE
```

**若 unit 没有 `EnvironmentFile`**，可仅依赖 `WorkingDirectory=/opt/lingji` + 默认相对路径 `data/inbox.db`（与上面 `mkdir` 一致即可）。

## 第 3 步：构建并部署 Gateway

在仓库根目录执行官方脚本：

```bash
cd "$REPO"
chmod +x scripts/deploy-gateway.sh
./scripts/deploy-gateway.sh --host "$LINGJI_SSH_HOST" --user "$LINGJI_SSH_USER"
```

脚本行为摘要：

1. `GOOS=linux GOARCH=amd64` 构建 `lingji-gateway`（**内嵌 Web v0.1.5**）
2. `scp` 到 VPS → `sudo install` 到 `/opt/lingji/lingji-gateway`
3. `sudo systemctl restart lingji-gateway`
4. 本机 + 公网 `curl` health

若构建在 WSL 且 Go 未装：

```bash
sudo apt-get update && sudo apt-get install -y golang-go
cd "$REPO/lingji-gateway" && go test ./... -count=1
```

## 第 4 步：Hermes 自动验收（部署后）

向用户索取 `LINGJI_AUTH_TOKEN`（`lingji-` 开头），或 `export` 已有变量：

```bash
: "${LINGJI_AUTH_TOKEN:?需要 token}"
export TOKEN="$LINGJI_AUTH_TOKEN"
export HOST=lingji.mygoal.tech
```

### 4.1 健康与静态版本

```bash
echo "=== health ==="
curl -sf "https://${HOST}/health" | python3 -m json.tool

echo
echo "=== Web v0.1.5 ==="
curl -sf "https://${HOST}/" | grep -o 'lingji-api.js?v=[^"]*'

echo
echo "=== inbox API 路由（空列表也应 200）==="
curl -sf "https://${HOST}/v1/inbox/threads?user_id=user-test&token=${TOKEN}" | python3 -m json.tool
```

**通过标准**：

| 检查 | 期望 |
|------|------|
| `/health` | `"status":"ok"` |
| `index.html` | `lingji-api.js?v=0.1.5` |
| `/v1/inbox/threads` | HTTP 200，`threads` 为数组（可为 `[]`） |
| `/v1/agents` | 含 `lingji-pc`（Agent 在线时还有 `lingji-laptop`） |

### 4.2 远端日志与 DB 文件

```bash
ssh ${LINGJI_SSH_KEY:+-i "$LINGJI_SSH_KEY"} "${LINGJI_SSH_USER}@${LINGJI_SSH_HOST}" bash -s <<'REMOTE'
set -euo pipefail
sudo systemctl is-active lingji-gateway
sudo journalctl -u lingji-gateway -n 30 --no-pager
ls -la /opt/lingji/data/ 2>/dev/null || ls -la /opt/lingji/
REMOTE
```

期望：服务 `active`；日志无 `inbox DB 打开失败`；部署后首次对话前 `inbox.db` 可能尚未创建（正常），有 WS 流量后应出现。

### 4.3 Go 单测（构建机，可选）

```bash
cd "$REPO/lingji-gateway" && go test ./... -count=1
```

## 第 5 步：请用户完成的配套与验收

将以下清单发给用户（Hermes 无法代劳部分）：

### 5.1 两端 Agent 升级

| 机器 | 操作 |
|------|------|
| 青铜剑 `lingji-pc` | `git pull` → 重启 Agent |
| 空城记 `lingji-laptop` | 同左（可参考 `laptop-fleet-1.5-acceptance-hermes.md`） |

Agent 变更：会话带 `agent_id`、回复带 `thread_id`。

### 5.2 浏览器验收（Fleet Phase 2）

1. 打开 `https://lingji.mygoal.tech/?token=<TOKEN>`，**强制刷新**（Ctrl+F5）
2. 在 **Laptop** 上发一条：`Fleet2 inbox 验收`
3. 手机同 token 打开 Web → 侧栏应出现带 **Laptop** 标签的会话
4. 点开该会话 → 能加载内容并路由到 Laptop
5. 切换 **Primary PC** 下拉 → 仍能列出 PC 侧会话（需曾在 PC 对话或切换过一次下拉以同步）

### 5.3 勾选

- [ ] Gateway 4.1 全部通过
- [ ] 两端 Agent 已 pull 并重启
- [ ] 5.2 手机能看到 Laptop 会话标签

## 失败排查

| 现象 | 处理 |
|------|------|
| `inbox DB 打开失败` | 检查 `/opt/lingji/data` 权限、`hermes` 用户、`LINGJI_INBOX_DB` |
| `/v1/inbox/threads` 404 | 二进制未更新到 Phase 2；重新 `deploy-gateway.sh` |
| Web 仍是 `v=0.1.4` | 二进制旧；确认 `git log` 含 `d81ad20` 后重构建部署 |
| inbox 一直空 | 正常直到有 WS 对话；让用户发消息；确认 Agent 已升级 |
| `401` on inbox API | token 错误或与 Gateway 不一致 |
| SSH 失败 | 向用户索取 `LINGJI_SSH_HOST` / 密钥，勿暴力重试 |

## 完成后汇报模板

```text
【Gateway Fleet Phase 2 部署汇报】
1. 部署 commit：
2. LINGJI_SSH_HOST：
3. systemctl status：
4. /health 与 Web 版本（v=0.1.5）：
5. /v1/inbox/threads 探测（200/失败）：
6. /opt/lingji/data 状态：
7. 用户勾选 5.3 结果：
8. 若失败：journalctl 最后 40 行摘要
```

## 一句话摘要

> 本地 `git pull` 到 `d81ad20+` → VPS 建 `/opt/lingji/data` → `./scripts/deploy-gateway.sh` → 验收 health + inbox API + Web `v=0.1.5` → 提醒用户两端 Agent 重启并做手机侧栏验收。

## 参考

- 设计摘要：[`fleet-phase2-inbox.md`](fleet-phase2-inbox.md)
- 部署脚本：[`scripts/deploy-gateway.sh`](../../scripts/deploy-gateway.sh)
- 笔记本 Agent：[`laptop-fleet-1.5-acceptance-hermes.md`](laptop-fleet-1.5-acceptance-hermes.md)
