# Fleet 4.0d-1 部署手册 — 空城记与青铜剑

> **版本**：2026-07-08 · 对应 Git `main` 含 **4.0a Job** + **fast-path 修复** + **4.0d-1 调度默认**  
> **读者**：**Hermes @ 青铜剑**、**Hermes @ 空城记**（按章节分头执行）  
> **设计**：[fleet-4.0d-remote-guardian-design.md](./fleet-4.0d-remote-guardian-design.md)  
> **勿**将本文全文粘贴给灵机 Agent 对话。

---

## 0. 本次发布包含什么

| 能力 | 说明 |
|------|------|
| **4.0a** | Gateway `LJ-*` Job 台账；`fleet_send_file` 自动建 Job；ACK 后推送结案 |
| **fast-path 修复** | 上传 + 文字（如「发给青铜剑」）不再误落本机 incoming |
| **4.0d-1** | Web 默认对话 **空城记 · 调度**；`scheduler_agent_id` 配置；Job 台账 scheduler 字段 |

**角色（定稿）：**

| 机器 | device_id | 角色 |
|------|-----------|------|
| **空城记** | `lingji-laptop` | **调度 Agent** — 用户唯一对话面 |
| **青铜剑** | `lingji-pc` | **值守执行机** — 上海留守，Agent + Hermes |
| 手机 Web | `user-*` | 入口；默认连空城记 |

---

## 1. 执行顺序（必读）

```text
① 用户 Windows：git push origin main（或 Hermes 在任一端 push）
② 青铜剑 Hermes：Gateway deploy（仅一次，含 Web v0.1.9）
③ 青铜剑 Hermes：pull + config + restart Agent
④ 空城记 Hermes：pull + config + restart Agent
⑤ 用户浏览器：Ctrl+F5 或 ?v=0.1.9
⑥ 按 §5 验收清单逐项勾
```

> **Gateway deploy 只需青铜剑（或有 SSH 权限的机器）执行一次。**  
> 空城记 **不要** 跑 `deploy-gateway.sh`，除非接管 Gateway 运维。

---

## 2. 青铜剑（lingji-pc · 上海值守）— Hermes 执行

### 2.1 前置

- WSL：`Ubuntu-24.04`，路径 `/mnt/e/LingjiPlan/LingjiZero`
- 已有 `lingji-agent/.venv`、`config/default_config.yaml`（**含密钥，勿提交 git**）
- SSH 密钥可部署 Gateway：`LINGJI_SSH_HOST` / `LINGJI_SSH_KEY`（见 `scripts/deploy-gateway.sh`）

### 2.2 拉代码

```bash
cd /mnt/e/LingjiPlan/LingjiZero
git fetch origin
git log -1 --oneline origin/main   # 应含 4.0d-1 相关 commit
git pull origin main
```

若 `git pull` 冲突：**停止**，汇报 `git status`，勿自行 merge。

### 2.3 合并 scheduler 配置（在现有 yaml 上追加）

**不要覆盖** 已有 `default_config.yaml`（含 API Key）。仅追加 `scheduler` 段：

```bash
cd /mnt/e/LingjiPlan/LingjiZero/lingji-agent
grep -q '^scheduler:' config/default_config.yaml || cat >> config/default_config.yaml <<'EOF'

scheduler:
  enabled: false
  scheduler_agent_id: lingji-laptop
  guardian_executor_ids: []
EOF
```

核对：

```bash
grep -A4 '^scheduler:' config/default_config.yaml
# 期望：enabled: false · scheduler_agent_id: lingji-laptop
grep display_name config/default_config.yaml   # 期望：青铜剑
grep device_id config/default_config.yaml    # 期望：lingji-pc
```

完整示例见 `config/default_config.yaml.example`。

### 2.4 部署 Gateway（含 Web v0.1.9）

```bash
cd /mnt/e/LingjiPlan/LingjiZero
export LINGJI_SSH_HOST=116.62.14.114   # 按实际
export LINGJI_SSH_KEY=~/.ssh/lingji_deploy
./scripts/deploy-gateway.sh
```

期望：脚本成功；生产 Web 静态资源更新。

### 2.5 重启青铜剑 Agent

```bash
cd /mnt/e/LingjiPlan/LingjiZero
./scripts/restart-agent-wsl.sh
tail -n 30 /tmp/lingji-agent.log | grep -E 'scheduler|Gateway|Device'
```

期望日志含：`Device: lingji-pc`；若有 scheduler 行：`scheduler_agent_id=lingji-laptop`。

```bash
cd /mnt/e/LingjiPlan/LingjiZero/lingji-agent
source .venv/bin/activate
python3 -m lingji_agent.main --status   # 期望：运行中
```

### 2.6 青铜剑 Windows 电源（离沪值守）

- **休眠：从不**；合盖：**不操作**或仅关屏
- 目标：Agent + Hermes bridge 7×24 可达

### 2.7 青铜剑 Hermes 完成汇报模板

```text
青铜剑 4.0d-1 部署完成：
- git: <commit hash>
- gateway deploy: OK
- agent --status: running
- scheduler: enabled=false, scheduler_agent_id=lingji-laptop
```

---

## 3. 空城记（lingji-laptop · 调度终端）— Hermes 执行

### 3.1 拉代码

```bash
cd /mnt/e/LingjiPlan/LingjiZero
git pull origin main
```

### 3.2 配置（调度 Agent）

若尚无 `default_config.yaml`，从笔记本示例复制后填密钥：

```bash
cd /mnt/e/LingjiPlan/LingjiZero/lingji-agent
test -f config/default_config.yaml || cp config/default_config.laptop.yaml.example config/default_config.yaml
# 编辑填入 llm.api_key、network.auth_token（勿 commit）
```

**必须** 含 `scheduler` 段（示例已写入 `default_config.laptop.yaml.example`）：

```yaml
scheduler:
  enabled: true
  scheduler_agent_id: lingji-laptop
  guardian_executor_ids:
    - lingji-pc
```

已有 yaml 时，同青铜剑用 append 方式合并（enabled 为 **true**）：

```bash
grep -q '^scheduler:' config/default_config.yaml || cat >> config/default_config.yaml <<'EOF'

scheduler:
  enabled: true
  scheduler_agent_id: lingji-laptop
  guardian_executor_ids:
    - lingji-pc
EOF
```

核对：

```bash
grep device_id config/default_config.yaml      # lingji-laptop
grep display_name config/default_config.yaml   # 空城记
grep -A5 '^scheduler:' config/default_config.yaml
```

### 3.3 重启空城记 Agent

```bash
cd /mnt/e/LingjiPlan/LingjiZero
./scripts/restart-agent-wsl.sh
python3 -m lingji_agent.main --status   # 在 .venv 下
```

期望日志：`scheduler: enabled=True` · `scheduler_agent_id=lingji-laptop`。

### 3.4 空城记 Hermes 完成汇报模板

```text
空城记 4.0d-1 部署完成：
- git: <commit hash>
- agent --status: running
- scheduler: enabled=true, guardians=[lingji-pc]
```

---

## 4. 用户侧（浏览器 / 手机）

1. 打开 `https://lingji.mygoal.tech?v=0.1.9` 或 **Ctrl+F5** 强刷  
2. 顶部下拉应默认：**空城记 · 调度**（非青铜剑）  
3. 若仍显示青铜剑：清除站点数据，或 DevTools → Application → localStorage 删除 `lingji_target_agent_v2` 后刷新  

---

## 5. 验收清单（部署后逐项打勾）

| # | 操作 | 期望 | ☐ |
|---|------|------|---|
| 1 | `GET /v1/agents?token=…` | `scheduler_agent_id` = `lingji-laptop`；双机 online | |
| 2 | Web 默认下拉 | **空城记 · 调度** | |
| 3 | 选空城记，上传文件 +「发给青铜剑」 | 青铜剑 incoming 有文件；`LJ-xxx 已完成` | |
| 4 | 仅上传、无文字 | 空城记本机「已保存到电脑」（fast-path） | |
| 5 | `GET /v1/jobs/LJ-xxx?token=…` | `scheduler_agent_id` = `lingji-laptop` | |

**失败时：**

- 文件仍落空城记 incoming → 确认 Agent 已 restart 且 commit ≥ fast-path 修复  
- Web 仍默认青铜剑 → Gateway 是否 deploy；浏览器是否 v0.1.9  
- 双机不在线 → 各自 `--status` + Gateway 日志  

---

## 6. 回滚（若验收失败）

```bash
cd /mnt/e/LingjiPlan/LingjiZero
git log -5 --oneline
git checkout <上一稳定 commit>   # 例如 1a0cbdf，须用户确认
./scripts/restart-agent-wsl.sh
# Gateway 回滚需重新 deploy 旧二进制，联系主程
```

勿 `git push --force` 除非用户明确要求。

---

## 7. 相关文档

| 文档 | 用途 |
|------|------|
| [fleet-4.0d-remote-guardian-design.md](./fleet-4.0d-remote-guardian-design.md) | 架构与 4.0d 路线图 |
| [fleet-4.0d-remote-guardian-runbook.md](./fleet-4.0d-remote-guardian-runbook.md) | 日常巡检与 break-glass |
| [fleet-4.0-job-workflow.md](./fleet-4.0-job-workflow.md) | Job API 工程摘要 |
| [laptop-fleet-3.1-display-name-via-agent.md](./laptop-fleet-3.1-display-name-via-agent.md) | display_name / Fleet 3.1 |

---

**文档版本**：4.0d-1 deploy · 2026-07-08
