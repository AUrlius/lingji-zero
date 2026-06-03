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

## 进程管理（PID 锁）

单实例锁文件：`/tmp/lingji-agent.pid`，防止多个 Agent 抢占 `lingji-pc`。

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
