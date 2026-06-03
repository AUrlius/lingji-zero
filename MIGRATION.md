# 代码迁入指南

> **状态：已于 2026-06-02 从 WSL 完成迁入。** 下文保留作再同步或新机器复现参考。

## 源路径（历史）

| 组件 | WSL 路径 |
|------|----------|
| Agent | `/home/unix20260308/lingji-agent/` |
| Gateway | `/home/unix20260308/lingji-gateway/` |
| Phone | `/home/unix20260308/lingji-phone/` |

## 目标布局

`E:\LingjiPlan\LingjiZero\{lingji-agent,lingji-gateway,lingji-phone}\`

## 再同步（WSL rsync 示例）

```bash
DEST=/mnt/e/LingjiPlan/LingjiZero

rsync -a \
  --exclude .venv --exclude .git --exclude __pycache__ --exclude .pytest_cache \
  --exclude lingji.db --exclude '*.pyc' \
  --exclude config/default_config.yaml \
  ~/lingji-agent/ "$DEST/lingji-agent/"

rsync -a --exclude .git --exclude __pycache__ --exclude lingji-gateway \
  ~/lingji-gateway/ "$DEST/lingji-gateway/"

rsync -a ~/lingji-phone/ "$DEST/lingji-phone/"
```

**勿复制：** `.venv/`、`lingji.db`、根目录 `lingji-gateway` 编译产物、`config/default_config.yaml`（含密钥）。

**应包含：** `config/default_config.yaml.example`、`tests/conftest.py`（排除脚本式 `integration_test.py` 的 pytest 收集）。

## 迁入后验收

1. `lingji-agent`：`pip install -e .` → `pytest tests/` → **105 passed**
2. `lingji-gateway`：`go test ./...` → 全绿；`go build -o lingji-gateway .`
3. `python tests/integration_test.py` → **6/6**（记录结果即可）
4. 更新 [../docs/internal/实现真相基线.md](../docs/internal/实现真相基线.md) §1–§2

## 配置与密钥

- 仓库内仅提交 `default_config.yaml.example`
- 本地：`cp config/default_config.yaml.example config/default_config.yaml` 后填入密钥
- 支持环境变量：`DEEPSEEK_API_KEY`、`LINGJI_AUTH_TOKEN` 等（见 `foundation/config.py`）
