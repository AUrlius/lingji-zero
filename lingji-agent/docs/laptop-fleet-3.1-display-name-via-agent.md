# 空城记 Fleet 3.1：display_name / aliases 部署（经浏览器指挥灵机 Agent）

> **范围**：仅 **空城记（lingji-laptop）**。  
> **青铜剑（lingji-pc）** 的命名由本机 **Hermes** 单独完成，本文档不包含。  
> **目的**：用灵机自身能力完成配置 + 拉代码 + 重启，顺带验收 Fleet 传文件与自然语言运维。  
> **版本基线**：空城记本地若仍停在 **`c89a95d`**，必须先 **`git pull` 到 `e82b5f1` 或更新** 再重启 Agent；仅改 `display_name` 而不升级代码，Web 会话切换修复（v0.1.6）不会生效。

---
## 一、给你（操作者）的三步流程

### 步骤 A：在青铜剑 Web 把本文档发到空城记

1. 浏览器打开 `https://lingji.mygoal.tech/?token=<你的token>`
2. 右上角目标电脑选 **青铜剑**（或 Primary PC / `lingji-pc`）
3. 发送（自然语言即可）：

```text
请用 fleet_send_file 把本机 WSL 路径下的部署文档发给空城记：
~/lingji-zero/lingji-agent/docs/laptop-fleet-3.1-display-name-via-agent.md
to_agent_id 填：空城记
```

4. 等待回复含 transfer 成功；文件会落到空城记 `~/Downloads/LingjiIncoming/`

> 若青铜剑仓库不在 `~/lingji-zero`，改用实际路径，例如：  
> `/mnt/e/LingjiPlan/LingjiZero/lingji-agent/docs/laptop-fleet-3.1-display-name-via-agent.md`

### 步骤 B：切换到空城记，粘贴「Agent 任务正文」

1. 同一浏览器，右上角改选 **空城记**（Laptop / `lingji-laptop`）
2. **新开一条对话**（避免与旧 thread 混淆）
3. 复制下方 **第二节「Agent 任务正文」** 整段，粘贴发送

### 步骤 C：看结果并验收

空城记 Agent 应汇报：配置已写入、**`git log -1` 为 `e82b5f1` 或更新**（不能仍是 `c89a95d`）、Agent 已重启、`/v1/agents` 里 `lingji-laptop` 带 `display_name: 空城记`。

你在手机/Web 下拉应看到 **「空城记 · lingji-laptop」**（或类似中文名）。

---

## 二、Agent 任务正文（粘贴给空城记灵机）

以下内容 **原样粘贴** 到空城记对话里即可：

```text
你是空城记（lingji-laptop）上的灵机 Agent。请在本机 WSL 中完成 Fleet 3.1 命名与代码更新，并重启 Agent。

【重要约束】
1. 所有 shell 命令在 WSL bash 中执行；Python 用 python3
2. 工作目录基准：REPO=~/lingji-zero（若不存在则尝试 /mnt/e/LingjiPlan/LingjiZero，以 pwd 确认后再继续）
3. Agent 代码目录：$REPO/lingji-agent
4. 只改 config/default_config.yaml，禁止 git commit/push
5. 必须保持 network.device_id=lingji-laptop，不得改成 lingji-pc
6. 禁止打印或回显完整 api_key / auth_token
7. 若触发 HITL：在**任意已登录设备**（手机或电脑浏览器）点击页面**顶部批准条**，不要仅打字「批准了」
8. **优先用 read_file + 单次 Python 改 YAML**（见第 2 步），避免链式多条 execute_command；`git pull` / `pip install` / 重启各可能触发一次 HITL，每次点顶部批准即可
9. 若 HITL 反复失败：改用 **Hermes 在空城记 WSL 直接执行**（见文档「三、Hermes 兜底」），比浏览器更稳

【第 0 步：确认路径与当前版本】
cd ~/lingji-zero 2>/dev/null || cd /mnt/e/LingjiPlan/LingjiZero
export REPO=$(pwd)
cd "$REPO/lingji-agent" && pwd
echo "=== 升级前 commit ==="
git log -1 --oneline
# 若已是 c89a95d，说明缺 e82b5f1（Web 会话缓存 + 别名提示），必须完成第 1 步 pull

【第 1 步：拉最新代码（必须离开 c89a95d）】
cd "$REPO"
git fetch origin && git pull origin main
echo "=== 升级后 commit ==="
git log -1 --oneline
# 通过标准：HEAD 至少为 e82b5f1（fix: per-agent session cache）
# 若 pull 后仍是 c89a95d：停止操作，汇报「GitHub 尚未 push，请用户在青铜剑让 Hermes 执行 git push origin main 后再 pull」
cd "$REPO/lingji-agent"
source .venv/bin/activate 2>/dev/null || true
pip install -e . -q

【第 2 步：写入 display_name 与 aliases】
在 $REPO/lingji-agent 下，用 Python 更新已有 default_config.yaml（保留原有 api_key、auth_token、device_id）：

cd "$REPO/lingji-agent"
source .venv/bin/activate 2>/dev/null || true
python3 <<'PY'
import yaml
from pathlib import Path
p = Path("config/default_config.yaml")
if not p.exists():
    raise SystemExit("缺少 config/default_config.yaml，请先 cp config/default_config.laptop.yaml.example config/default_config.yaml 并填入密钥")
data = yaml.safe_load(p.read_text(encoding="utf-8"))
net = data.setdefault("network", {})
assert net.get("device_id") == "lingji-laptop", f"device_id 必须是 lingji-laptop，当前={net.get('device_id')}"
net["display_name"] = "空城记"
net["aliases"] = ["空城记", "笔记本", "Laptop"]
p.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False), encoding="utf-8")
print("ok: display_name=", net["display_name"], "device_id=", net["device_id"])
PY

【第 3 步：校验配置（不打印密钥）】
python3 -c "
import yaml
c=yaml.safe_load(open('config/default_config.yaml'))
assert c['network']['device_id']=='lingji-laptop'
assert c['network']['display_name']=='空城记'
assert '空城记' in c['network'].get('aliases',[])
print('config validation ok')
"

【第 4 步：重启 Agent】
cd "$REPO/lingji-agent"
source .venv/bin/activate
python3 -m lingji_agent.main --stop 2>/dev/null || true
nohup python3 -m lingji_agent.main >> ~/.lingji/agent.log 2>&1 &
sleep 3
python3 -m lingji_agent.main --status

【第 5 步：验收】
curl -sf https://lingji.mygoal.tech/health
curl -sf "https://lingji.mygoal.tech/v1/agents?token=$(python3 -c "import yaml;print(yaml.safe_load(open('config/default_config.yaml'))['network']['auth_token'])")" | python3 -m json.tool | grep -A2 lingji-laptop

【汇报格式】
请用中文简要汇报：
- REPO 实际路径
- **升级前 / 升级后** git log -1 的 commit（必须说明是否已从 c89a95d 升到 e82b5f1+）
- display_name / device_id 是否生效
- Agent 是否在运行
- /v1/agents 里 lingji-laptop 是否在线且带 display_name
```

---

## 三、Hermes 兜底（推荐：绕过浏览器 HITL）

若浏览器审批条异常或 `execute_command` 链式卡住，在**空城记 WSL** 让 Hermes 直接执行：

```bash
export REPO=~/lingji-zero   # 或 /mnt/e/LingjiPlan/LingjiZero
cd "$REPO" && git fetch origin && git pull origin main
cd "$REPO/lingji-agent" && source .venv/bin/activate && pip install -e . -q
# 写入 display_name（保留 api_key / auth_token / device_id=lingji-laptop）
python3 <<'PY'
import yaml
from pathlib import Path
p = Path("config/default_config.yaml")
data = yaml.safe_load(p.read_text(encoding="utf-8"))
net = data.setdefault("network", {})
assert net.get("device_id") == "lingji-laptop"
net["display_name"] = "空城记"
net["aliases"] = ["空城记", "笔记本", "Laptop"]
p.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False), encoding="utf-8")
print("ok")
PY
python3 -m lingji_agent.main --stop 2>/dev/null || true
nohup python3 -m lingji_agent.main >> ~/.lingji/agent.log 2>&1 &
```

完成后按 **第五节验收清单** 勾选即可。

---

## 四、可选：不依赖传文件，直接粘贴

若步骤 A 传文件失败，可 **跳过 A**，直接在空城记对话粘贴 **第二节全文**（Agent 不读 incoming 里的 md 也能完成）。

---

## 五、与青铜剑 Hermes 的分工

| 机器 | 命名配置 | 执行者 |
|------|----------|--------|
| **青铜剑** `lingji-pc` | `display_name: 青铜剑`，aliases 含「青铜剑」「主PC」 | **Hermes**（SSH/WSL，不经过本文档） |
| **空城记** `lingji-laptop` | `display_name: 空城记`，aliases 含「空城记」「笔记本」 | **浏览器 → 空城记灵机 Agent**（本文档） |

青铜剑 Hermes 参考命令（给你自行交给 Hermes，**勿粘贴给空城记 Agent**）：

```bash
export REPO=~/lingji-zero   # 或 /mnt/e/LingjiPlan/LingjiZero
cd "$REPO/lingji-agent"
# 在 default_config.yaml 的 network 下增加 display_name / aliases，device_id 保持 lingji-pc
python3 -m lingji_agent.main --stop && nohup python3 -m lingji_agent.main >> ~/.lingji/agent.log 2>&1 &
```

---

## 六、验收清单（用户勾选）

| # | 操作 | 期望 |
|---|------|------|
| 1 | 手机下拉 | 同时看到 **青铜剑**、**空城记**（非仅 Primary PC / Laptop） |
| 2 | 选空城记问「Fleet 在线设备有哪些」 | 列表含 `lingji-pc（青铜剑）` 与 `lingji-laptop（空城记）` |
| 3 | 选空城记：「把 Downloads 里某文件发给青铜剑」 | `fleet_send_file` 成功，青铜剑 incoming 有文件 |
| 4 | 青铜剑发图 → 切空城记 → 再切回青铜剑 | 发图会话记录仍在（Web v0.1.6+） |

---

## 七、故障排查

| 现象 | 处理 |
|------|------|
| **`git pull` 后仍是 `c89a95d`** | GitHub 上还没有 `e82b5f1`；先在青铜剑让 **Hermes `git push origin main`**，空城记再 `git pull` |
| Agent 说找不到 `~/lingji-zero` | 让它 `ls ~` / `ls /mnt/e/LingjiPlan/LingjiZero` 确认 REPO 后再 `cd` |
| `device_id` 变成 lingji-pc | **停止**，改回 `lingji-laptop` 再重启 |
| `/v1/agents` 无 display_name | 确认 Gateway 已 deploy Phase 3.1+；Agent AUTH 已带 display_name |
| HITL 批准条闪退 / 打字无效 | Gateway Web **v0.1.7+** 顶部 `#hitlDock` 常驻；必须点按钮，或打字「批准」触发自动映射 |
| 传文件仍不认「青铜剑」 | 确认青铜剑 Hermes 也已配置 display_name 并重启 |

---

**文档版本**：Fleet 3.1 · 2026-07-07  
**仓库路径**：`lingji-agent/docs/laptop-fleet-3.1-display-name-via-agent.md`
