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

```bash
git clone https://github.com/AUrlius/lingji-zero.git   # 或 rsync 源码
cd lingji-zero/lingji-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp config/default_config.yaml.example config/default_config.yaml
# 编辑 default_config.yaml：
#   network.device_id: lingji-laptop
#   llm.api_key / network.auth_token 与主 PC 相同
python3 -m lingji_agent.main
```

无需改云防火墙（Agent 主动连 `lingji.mygoal.tech:443`）。Gateway 需已部署含 `/v1/agents` 与 `target_agent_id` 路由的版本。

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
