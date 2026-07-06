# Hermes 任务：笔记本部署 lingji-laptop Agent

> **用法**：把本文件交给笔记本上的 Hermes 执行（粘贴全文，或 `~/.hermes/tasks/lingji-laptop-deploy.md`）。  
> **前提**：笔记本 WSL 已 `git clone` 仓库（默认 `~/lingji-zero`；路径不同则先 `cd` 到实际目录）。

## 任务目标

在**笔记本 WSL** 上启动第二个灵机 Agent：

- `device_id` = **`lingji-laptop`**（不能与青铜剑的 `lingji-pc` 相同）
- 连接生产 Gateway：`lingji.mygoal.tech:443`
- 成功后，手机 Web `https://lingji.mygoal.tech` 下拉应出现 **Laptop**，且 `/v1/agents` 返回两台设备

## 重要约束（必读）

1. **只改本机配置，不要改代码，不要 git commit/push**
2. **`config/default_config.yaml` 含密钥，已在 `.gitignore`，禁止提交**
3. **禁止把掩码形式的 Key 写入配置**（如 `sk-29e...0286`）。必须向用户索取**完整** `DEEPSEEK_API_KEY` 和 `LINGJI_AUTH_TOKEN`，或使用用户已 `export` 的环境变量
4. **`device_id` 必须是 `lingji-laptop`**，绝不能是 `lingji-pc`
5. 所有命令在 **WSL bash** 中执行，Python 用 `python3`

## 第 0 步：确认仓库路径

```bash
# 若用户未说明路径，先找仓库
ls ~/lingji-zero/lingji-agent/pyproject.toml 2>/dev/null || ls ~/lingji-zero/lingji-agent/setup.py 2>/dev/null
# 找到后：
export REPO=~/lingji-zero    # 按实际路径修改
cd "$REPO/lingji-agent"
pwd
git log -1 --oneline
```

期望：在 `lingji-agent` 目录，且 `git log` 能看到较新的 commit（含 multi-PC / cache-fix）。

## 第 1 步：Python 虚拟环境与依赖

```bash
cd "$REPO/lingji-agent"

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

验证：

```bash
python3 -c "import lingji_agent; print('import ok')"
```

## 第 2 步：生成本机配置文件

**含义**：仓库里 `.example` 是模板，Agent 只读 `default_config.yaml`。  
笔记本专用模板已写好 `device_id: lingji-laptop`，复制并改名即可。

```bash
cd "$REPO/lingji-agent"

cp config/default_config.laptop.yaml.example config/default_config.yaml
ls -la config/default_config.yaml
grep device_id config/default_config.yaml
```

期望输出含：`device_id: lingji-laptop`

- **不要**用 `default_config.yaml.example`（那是 `lingji-pc` 主 PC 模板）
- **不要**从青铜剑拷贝整份 `default_config.yaml`（会把 `device_id` 弄成 `lingji-pc`）

## 第 3 步：填入密钥

向用户确认两个值（若用户已在 shell 里 `export`，可直接用环境变量）：

| 变量 | 用途 | 与谁相同 |
|------|------|----------|
| `DEEPSEEK_API_KEY` | DeepSeek LLM | 与青铜剑相同（完整 `sk-` 开头字符串） |
| `LINGJI_AUTH_TOKEN` | Gateway 认证 | 与青铜剑、服务器相同（`lingji-` 开头） |

**推荐写法**（避免 Hermes 把掩码写进文件）——让用户在终端输入，或用户自行 export 后执行：

```bash
cd "$REPO/lingji-agent"
source .venv/bin/activate

# 若用户已 export，跳过 read；否则交互读取（不回显）
: "${DEEPSEEK_API_KEY:=$(read -rsp 'DEEPSEEK_API_KEY: ' k; echo; echo "$k")}"
: "${LINGJI_AUTH_TOKEN:=$(read -rsp 'LINGJI_AUTH_TOKEN: ' t; echo; echo "$t")}"

python3 <<'PY'
import os, yaml
from pathlib import Path
p = Path("config/default_config.yaml")
data = yaml.safe_load(p.read_text(encoding="utf-8"))
data.setdefault("llm", {})["api_key"] = os.environ["DEEPSEEK_API_KEY"]
data.setdefault("network", {})["auth_token"] = os.environ["LINGJI_AUTH_TOKEN"]
data["network"]["device_id"] = "lingji-laptop"  # 强制确认
p.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False), encoding="utf-8")
print("config written, device_id=", data["network"]["device_id"])
PY
```

写入后检查（**不要**把完整 key 打印到日志；只检查非空）：

```bash
python3 -c "
import yaml
c=yaml.safe_load(open('config/default_config.yaml'))
assert c['network']['device_id']=='lingji-laptop'
assert c['llm']['api_key'].startswith('sk-') and '...' not in c['llm']['api_key']
assert c['network']['auth_token'].startswith('lingji-')
print('config ok')
"
```

## 第 4 步：启动 Agent

```bash
cd "$REPO/lingji-agent"
source .venv/bin/activate

# 若已有旧进程，先停
python3 -m lingji_agent.main --stop 2>/dev/null || true

# 前台启动（便于看日志）；确认无误后可改后台
python3 -m lingji_agent.main
```

期望日志含类似：**已连接 Gateway: wss://lingji.mygoal.tech:443/ws**

另开终端检查状态：

```bash
cd "$REPO/lingji-agent" && source .venv/bin/activate
python3 -m lingji_agent.main --status
```

## 第 5 步：验收（必须全部通过）

在 WSL 执行（`TOKEN` 用第 3 步的 `LINGJI_AUTH_TOKEN`）：

```bash
export TOKEN='lingji-替换为实际token'

echo "=== health ==="
curl -sf https://lingji.mygoal.tech/health

echo
echo "=== agents ==="
curl -sf "https://lingji.mygoal.tech/v1/agents?token=$TOKEN" | python3 -m json.tool
```

**通过标准**：

- `/health` → `"status":"ok"`
- `/v1/agents` → `agents` 数组里**同时有** `lingji-pc` 和 `lingji-laptop`
- 笔记本 Agent 日志无反复 401 / 认证失败

**用户侧（浏览器）**：

1. 打开 `https://lingji.mygoal.tech/?token=<同一token>`
2. 右上角「目标电脑」下拉应可选 **Primary PC** 和 **Laptop**
3. 选 Laptop 发一条消息，应由笔记本 Agent 回复
4. **会话同步**：手机与青铜剑 Web 使用**相同 token** 且均选 **Primary PC** 时，侧栏会话应一致（client_id 形如 `user-xxxxxxxx`）；与 Laptop 的对话仍在 Laptop Agent 侧，手机暂不可见（Fleet 第二期）

## 失败排查

| 现象 | 处理 |
|------|------|
| WebSocket 401 | 检查 `auth_token` 是否完整、与 Gateway 一致；勿含引号转义 `\"` |
| `/v1/agents` 只有 `lingji-pc` | 笔记本 Agent 未连上；查 `--status` 和启动日志 |
| 两台都是 `lingji-pc` | `device_id` 配错；改回 `lingji-laptop` 并重启 |
| LLM 报错 / 无回复 | `api_key` 可能是掩码；让用户重新提供完整 sk- key |
| `Address already in use` / PID 锁 | `python3 -m lingji_agent.main --stop` 后重试 |
| ChromaDB 首次慢 | 正常，等待 1–3 分钟 ONNX 模型下载，Gateway 连接可先成功 |

## 完成后汇报给用户

请汇总：

1. 仓库路径、`device_id`、Agent 是否在运行
2. `/v1/agents` 完整 JSON
3. 是否能在 Web 下拉看到 Laptop
4. 若失败：最后 20 行 Agent 日志 + 具体报错

**不要**在汇报中粘贴完整 API Key 或 auth_token。

## 一句话摘要

> 在笔记本 WSL 的 `lingji-agent` 目录：venv → `pip install -e .` → `cp config/default_config.laptop.yaml.example config/default_config.yaml` → 填入完整 DeepSeek key 与同 Gateway token → 确认 `device_id=lingji-laptop` → 启动 Agent → curl `/v1/agents` 应出现 `lingji-laptop`。
