# lingji-agent

Python Agent Client：WSL 本机运行，经 Cloudflare 连接云端 Gateway，调用 DeepSeek。

## 快速启动（WSL）

```bash
cd /mnt/e/LingjiPlan/LingjiZero/lingji-agent
source .venv/bin/activate
export DEEPSEEK_API_KEY="sk-..."
export LINGJI_AUTH_TOKEN="lingji-..."

python -m lingji_agent.main
```

生产 Gateway：`lingji.mygoal.tech:443`（见 `config/default_config.yaml` 或环境变量 `LINGJI_GATEWAY_HOST` / `LINGJI_GATEWAY_PORT`）。

## 多 PC 部署（第二台电脑 / 笔记本）

每台电脑独立运行一个 Agent，使用**不同的 `device_id`**，手机 Web 顶部可选择目标电脑。

| 机器 | 建议 `device_id` | 说明 |
|------|------------------|------|
| 主 PC | `lingji-pc` | 默认目标 |
| 第二台 PC / 笔记本 | `lingji-laptop` | 或其它 `lingji-*` 唯一 ID |

**笔记本 WSL 步骤：**

详见 [docs/laptop-deploy-hermes.md](docs/laptop-deploy-hermes.md)（可交给 Hermes 逐步执行）。

```bash
git clone https://github.com/AUrlius/lingji-zero.git   # 或 rsync 源码
cd lingji-zero/lingji-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp config/default_config.laptop.yaml.example config/default_config.yaml
# 编辑 default_config.yaml：填入 llm.api_key / network.auth_token（与主 PC 相同）
python3 -m lingji_agent.main
```

无需改云防火墙（Agent 主动连 `lingji.mygoal.tech:443`）。Gateway 需已部署含 `/v1/agents` 与 `target_agent_id` 路由的版本。

## 多入口 Web（手机 + 各 PC 浏览器）

Fleet 第一期：各 Web 入口使用**相同 Gateway token** 时，自动得到相同 **client_id**（形如 `user-xxxxxxxx`），在**同一台目标 PC**（如都选 Primary PC）上**共享会话列表与历史**。

1. 每台设备首次用完整链接登录：`https://lingji.mygoal.tech/?token=YOUR_TOKEN`
2. 之后可书签裸域名 `https://lingji.mygoal.tech/`（token 已写入 localStorage）
3. 可选固定身份：`?client_id=my-name`（高级用法）
4. 与不同 PC 的对话仍分别在各自 Agent 上（第二期 Gateway 收件箱将合并）
5. **多端同时在线**（v0.1.4+）：每浏览器独立 `conn-*` 连接，共享 `user-*` 身份；手机与 PC Web 可同时「已连接」

## 进程管理（PID 锁）

单实例锁文件：`/tmp/lingji-agent.pid`，防止**同一台机器**上多个进程抢占同一 `device_id`。

```bash
# 查看是否在运行
python -m lingji_agent.main --status

# 停止（SIGTERM，清理 PID 文件）
python -m lingji_agent.main --stop

# 重启
python -m lingji_agent.main --stop && python -m lingji_agent.main
```

`Ctrl+C` 正常退出时会自动释放 PID 锁。

## 记忆层（ChromaDB）

启用时向量库在**后台预热**，不阻塞 Gateway 连接。首次运行可能下载 ONNX 嵌入模型（约 1–3 分钟），后续启动使用本地缓存。

## 测试

```bash
python -m pytest tests/ -q
python tests/integration_test.py   # 需本机 Gateway，非默认 pytest
```

详见 [`项目移交手册.md`](../../项目移交手册.md)。
