# Hermes 任务：空城记 Fleet 1.5 验收（lingji-laptop）

> **验收状态：已通过**（2026-07-06，发起人确认全项勾选）  
> **用法**：把本文件交给**空城记笔记本**上的 Hermes 执行（粘贴全文，或保存为 `~/.hermes/tasks/lingji-laptop-fleet-1.5.md`）。  
> **前提**：笔记本 WSL 已按 [`laptop-deploy-hermes.md`](laptop-deploy-hermes.md) 部署过 Agent，且 `device_id=lingji-laptop`。若从未部署，先完成那份文档再回来。

## 任务目标

将空城记笔记本 Agent **更新到 Fleet 1.5** 并跑通验收：

| 项 | 说明 |
|----|------|
| 目标 commit | `5c14a2c` — `feat(fleet): stable user_id and multi-device Web v0.1.4` |
| 生产 Gateway | 已部署 Web `?v=0.1.4`（`CONNECTION_ID` + `user_id` fan-out） |
| 本机职责 | `git pull` → 重装依赖 → **重启 Agent**（配置一般不用改） |
| 验收重点 | 两台 Agent 同时在线；Web 显示 `user-*`；手机与电脑 Web **互不踢线**；选 Laptop 能对话 |

**Fleet 1.5 是什么（一句话）**：同一 token 对应稳定账号 `user-xxxxxxxx`；每个浏览器用独立连接 `conn-*`；Gateway 按 `user_id` 扇出，手机与多台电脑 Web 可同时「已连接」。

## 重要约束（必读）

1. **只改本机配置（若已存在则通常不动），不要改代码，不要 git commit/push**
2. **`config/default_config.yaml` 含密钥，禁止提交、禁止在汇报里粘贴完整 Key**
3. **`device_id` 必须保持 `lingji-laptop`**，绝不能改成 `lingji-pc`
4. 所有命令在 **WSL bash** 中执行，Python 用 `python3`
5. 若 `git pull` 有冲突，**停止并汇报用户**，不要强行 merge

## 第 0 步：确认仓库与当前版本

```bash
export REPO=~/lingji-zero    # 按实际路径修改
cd "$REPO"
git fetch origin
git log -1 --oneline
git log -1 --oneline 5c14a2c 2>/dev/null || git log --oneline | head -5
```

**期望**：`HEAD` 为 `5c14a2c` 或更新的 `main`（且包含该 commit）。

若落后：

```bash
cd "$REPO"
git pull origin main
git log -1 --oneline
```

确认含有 Fleet 相关改动（任选其一应能 grep 到）：

```bash
grep -q 'CONNECTION_ID' lingji-gateway/web/js/lingji-api.js && echo "OK: Web Fleet 1.5 JS"
grep -q '_resolve_web_client' lingji-agent/src/lingji_agent/main.py && echo "OK: Agent user_id routing"
```

## 第 1 步：更新 Python 依赖

```bash
cd "$REPO/lingji-agent"
source .venv/bin/activate
pip install -U pip
pip install -e .
```

跑与本机相关的单测（可选但推荐）：

```bash
cd "$REPO/lingji-agent"
source .venv/bin/activate
python3 -m pytest tests/test_web_client_ids.py -q
```

期望：`2 passed`

## 第 2 步：确认配置（通常无需修改）

Fleet 1.5 **不要求**改 `default_config.yaml`。仅核对关键字段：

```bash
cd "$REPO/lingji-agent"
python3 -c "
import yaml
c = yaml.safe_load(open('config/default_config.yaml'))
assert c['network']['device_id'] == 'lingji-laptop', c['network']['device_id']
assert c['network']['gateway_host'] == 'lingji.mygoal.tech'
assert c['network']['auth_token'].startswith('lingji-')
assert c['llm']['api_key'].startswith('sk-') and '...' not in c['llm']['api_key']
print('config ok: device_id=lingji-laptop')
"
```

| 检查项 | 期望值 |
|--------|--------|
| `network.device_id` | `lingji-laptop` |
| `network.gateway_host` | `lingji.mygoal.tech` |
| `network.auth_token` | 与青铜剑、Gateway **相同** 的 `lingji-` token |
| `llm.api_key` | 完整 `sk-` 字符串（非掩码） |

若配置文件不存在或 `device_id` 错误，回到 [`laptop-deploy-hermes.md`](laptop-deploy-hermes.md) 第 2–3 步修复，**不要**从青铜剑拷贝整份配置。

## 第 3 步：重启 Agent

```bash
cd "$REPO/lingji-agent"
source .venv/bin/activate

python3 -m lingji_agent.main --stop 2>/dev/null || true
sleep 2

# 前台启动便于看日志；确认无误后可由用户改为后台
python3 -m lingji_agent.main
```

期望日志含：

- `已连接 Gateway: wss://lingji.mygoal.tech:443/ws`
- 无反复 `401` / 认证失败

另开终端：

```bash
cd "$REPO/lingji-agent" && source .venv/bin/activate
python3 -m lingji_agent.main --status
```

## 第 4 步：Hermes 自动验收（WSL）

向用户索取 `LINGJI_AUTH_TOKEN`（`lingji-` 开头），或使用用户已 `export` 的变量：

```bash
: "${LINGJI_AUTH_TOKEN:?请先 export LINGJI_AUTH_TOKEN 或向用户索取}"
export TOKEN="$LINGJI_AUTH_TOKEN"
```

### 4.1 生产 Gateway / Web 静态资源

```bash
echo "=== health ==="
curl -sf https://lingji.mygoal.tech/health

echo
echo "=== agents（须同时有 lingji-pc 与 lingji-laptop）==="
curl -sf "https://lingji.mygoal.tech/v1/agents?token=$TOKEN" | python3 -m json.tool

echo
echo "=== Web JS Fleet 1.5 特征 ==="
curl -sf 'https://lingji.mygoal.tech/js/lingji-api.js?v=0.1.4' | grep -E 'CONNECTION_ID|USER_ID|user_id' | head -5

echo
echo "=== index 版本 ==="
curl -sf 'https://lingji.mygoal.tech/' | grep -o 'lingji-api.js?v=[^"]*'
```

**通过标准**：

| 检查 | 通过条件 |
|------|----------|
| `/health` | `"status":"ok"` |
| `/v1/agents` | `agents` 数组**同时**含 `lingji-pc` 和 `lingji-laptop` |
| `lingji-api.js?v=0.1.4` | 含 `CONNECTION_ID`、`USER_ID`、`user_id` |
| `index.html` | script 引用 `?v=0.1.4` |

### 4.2 Agent 代码版本

```bash
cd "$REPO"
git merge-base --is-ancestor 5c14a2c HEAD && echo "OK: commit >= 5c14a2c" || echo "FAIL: 需要 git pull"
```

### 4.3 WebSocket 连通

```bash
cd "$REPO/lingji-agent"
source .venv/bin/activate
python3 <<'PY'
import asyncio
import os
import websockets

TOKEN = os.environ["TOKEN"]

async def main():
    uri = f"wss://lingji.mygoal.tech/ws?token={TOKEN}"
    async with websockets.connect(uri) as ws:
        print("OK: WebSocket connected")

asyncio.run(main())
PY
```

## 第 5 步：请用户做的浏览器验收（Hermes 无法代劳）

把以下清单**原样发给用户**，由用户在青铜剑 + 空城记 + 手机上操作：

### 5.1 准备

1. 确认三台设备使用**同一个** URL token：  
   `https://lingji.mygoal.tech/?token=<LINGJI_AUTH_TOKEN>`
2. 若曾打开过旧版页面，建议**强制刷新**（Ctrl+F5）或清除站点数据后重开带 token 的链接。
3. 青铜剑 Agent 也应已重启到 Fleet 1.5（用户侧主 PC 应已完成）。

### 5.2 多端同时在线（Fleet 1.5 核心）

| 步骤 | 操作 | 期望 |
|------|------|------|
| A | 手机打开 Web，记下右上角状态 | 显示 **`已连接 (user-xxxxxxxx)`**（不是裸 `phone-xxxx`） |
| B | 青铜剑电脑浏览器打开同一 token | 同样 **`已连接 (user-xxxxxxxx)`**，**与手机 x 相同** |
| C | 保持 A、B 不关闭，观察 30 秒 | **两边都保持已连接**，不会互相踢下线 |
| D | 空城记也可开第三个浏览器 tab 同 token | 三个入口均可同时在线 |

### 5.3 路由到笔记本

| 步骤 | 操作 | 期望 |
|------|------|------|
| E | 任一端 Web，「目标电脑」选 **Laptop** | 下拉有 Primary PC 与 Laptop |
| F | 发送：`空城记 Fleet1.5 验收 ping` | 由 **lingji-laptop** 回复（日志在笔记本 Agent） |
| G | 切回 **Primary PC** 发一条消息 | 由青铜剑 Agent 回复 |

### 5.4 会话同步（Fleet 第一期，顺带确认）

| 步骤 | 操作 | 期望 |
|------|------|------|
| H | 手机与青铜剑 Web，均选 **Primary PC** | 侧栏会话列表**一致** |
| I | 在 Primary PC 新建会话并发消息 | 另一端刷新/重连后能看到同一会话 |

**说明**：Laptop 上的对话存在**笔记本本机** `lingji.db`，手机暂时**看不到** Laptop 会话——这是预期行为，跨 Agent 统一列表要等 Fleet **第二期** inbox。

### 5.5 验收结论勾选

请用户回复 Hermes / 发起人：

- [ ] 4.1 `/v1/agents` 双机在线
- [ ] 5.2 手机 + 电脑 Web 同 `user-*` 且互不踢线
- [ ] 5.3 选 Laptop 能收到回复
- [ ] 5.4 Primary PC 会话在手机与电脑 Web 一致

四项全勾 = **空城记 Fleet 1.5 验收通过**。

## 失败排查

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| `/v1/agents` 只有 `lingji-pc` | 笔记本 Agent 未运行或未连上 | 查 `--status`、启动日志、token |
| Web 仍显示 `phone-xxxx` 或无 `user-` | 浏览器缓存旧 JS | 用带 `?v=0.1.4` 的页面；Ctrl+F5；或无痕窗口 |
| 手机与电脑互踢 | Agent 未更新到 1.5，或 Web 非 0.1.4 | 笔记本 `git pull` + 重启；curl 检查 JS |
| 选 Laptop 无回复 | 路由到错机或 LLM key 无效 | 确认下拉为 Laptop；查笔记本 Agent 日志 |
| `user-` 与手机不一致 | token 不同 | 必须用**完全相同**的 `lingji-` token |
| git pull 冲突 | 本机改过 tracked 文件 | 停止，汇报 `git status`，不要自行解决 |
| pytest 失败 | 代码未更新完整 | `git pull` 后重装 `pip install -e .` |

## 完成后汇报模板

请汇总给用户（**勿粘贴完整密钥**）：

```text
【空城记 Fleet 1.5 验收汇报】
1. 仓库路径：
2. git HEAD：
3. device_id：
4. Agent 状态（--status）：
5. /v1/agents 摘要（device_id 列表即可）：
6. Web JS 版本（curl index / lingji-api.js）：
7. 用户勾选 5.5 哪几项通过 / 哪几项失败：
8. 若失败：笔记本 Agent 最后 30 行日志 + 浏览器现象描述
```

## 一句话摘要

> 空城记 WSL：`git pull` 到含 `5c14a2c` → `pip install -e .` → 确认 `device_id=lingji-laptop` 与 token 未变 → 重启 Agent → `/v1/agents` 双机在线 → 用户用手机+电脑同 token 验证 `user-*` 且不互踢 → 选 Laptop 能对话。

## 参考

- 初装文档：[`laptop-deploy-hermes.md`](laptop-deploy-hermes.md)
- Fleet 计划：`LingjiPlan/docs/internal/灵机Fleet连通实施计划.md`（Phase 1 + 1.5）
- 远端自检脚本（青铜剑/WSL 可跑）：`LingjiZero/scripts/verify-web-cache-fix.sh`
