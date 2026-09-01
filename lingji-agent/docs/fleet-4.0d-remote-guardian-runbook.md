# Fleet 4.0d — 离沪值守 Runbook

> **部署（首次 / 发版）**：[fleet-4.0d-1-deploy-空城记与青铜剑.md](./fleet-4.0d-1-deploy-空城记与青铜剑.md) ← **pull 后按此文档分机执行**  
> **设计定稿**：[fleet-4.0d-remote-guardian-design.md](./fleet-4.0d-remote-guardian-design.md)  
> **用途**：日常巡检与 break-glass；**勿**粘贴给调度 Agent 当对话指令。
>
> **2026-08-31：** 主路径执行 = 青铜剑 Agent 收 `JOB_DELEGATE` 后跑 `scripts/playbooks/*.sh`。  
> Hermes **无入站端口**；飞书↔Hermes 仅 break-glass。档 B（Hermes CLI）未接入 Job。  
> **重启后补报：** `agent.restart` 会杀掉当前进程；回执写入 `lingji-agent/data/pending_job_report.json`，新进程连上 Gateway 后再 REPORT。

---

## 角色速查

| 机器 | device_id | 角色 |
|------|-----------|------|
| 青铜剑（上海） | `lingji-pc` | **值守执行机** — Agent 跑 playbook；Hermes 仅 break-glass |
| 空城记（随用户） | `lingji-laptop` | **调度 / 秘书** — 用户唯一对话面 |
| 手机 Web | `user-*` | 董事长办公桌，等同 user_id；默认只聊秘书 |

**铁律：** 用户 → 秘书（空城记）→ Job `LJ-*` → 青铜剑 playbook → REPORT。**不**用户直聊 Hermes / 直选青铜剑。

---

## A. 上海青铜剑 — 一次性部署

```bash
# 在青铜剑 WSL
cd /mnt/e/LingjiPlan/LingjiZero
git pull origin main

# config：display_name + incoming_dir（勿提交密钥）
grep -E 'display_name|incoming_dir|device_id' lingji-agent/config/default_config.yaml

# Agent 自启（按环境选手册二选一）
./scripts/restart-agent-wsl.sh
# TODO: systemd / Task Scheduler 见 4.0d 实现后补充

# 电源：Windows 设置 → 休眠「从不」；合盖「不操作」或仅关屏
```

**Hermes：** 青铜剑 Hermes Gateway 只出站到飞书，**不要**开入站端口或把 OpenClaw HTTP 暴露到公网。Job 主路径不依赖 Hermes。

---

## B. 空城记 — 调度终端

```bash
cd /mnt/e/LingjiPlan/LingjiZero
git pull origin main
./scripts/restart-agent-wsl.sh
```

Web 使用 `https://lingji.mygoal.tech`；目标态默认连 **空城记（调度）**，非青铜剑。

---

## C. Deploy 链（有代码变更时）

```bash
# 青铜剑 WSL
cd /mnt/e/LingjiPlan/LingjiZero
git pull origin main
./scripts/deploy-gateway.sh    # 需 SSH / 密钥
./scripts/restart-agent-wsl.sh

# 空城记同步 pull + restart
```

---

## D. 每日健康检查（playbook：`agent.status`）

产品路径：Web 对秘书说「检查上海 Agent 状态」→ `job_invoke` → `LJ-*` → 青铜剑跑脚本。

手动等价（青铜剑 WSL）：

```bash
cd /mnt/e/LingjiPlan/LingjiZero
bash scripts/playbooks/agent_status.sh
# 末行 STATUS=ok 或 STATUS=fail
```

期望：`lingji-pc`、`lingji-laptop` 均在 `agents` 列表。

---

## E. 离沪前实机验收（4 条）

1. **手机 Web** → 调度 Agent：「把这个文件发到上海青铜剑」→ `LJ-xxx 已完成`  
2. 「检查上海 Agent 状态」→ 侧栏出现 `LJ-*`，对话内步骤卡 completed/failed；**无** `execute_command(find)` 僵尸 HITL  
3. 纯上传无文字 → 仍「已保存到电脑」（fast-path）  
4. 上传 +「发给青铜剑」→ **不应**落本机 incoming（`65d37d1`+）

---

## F. Break-glass（仅调度与 Gateway 均不可用）

用户可直接让 **Hermes @ 青铜剑** 执行 §A/C 命令；**不计入** Job 台账，事后补记运维日志。

---

## G. 相关文档

- [fleet-4.0d-1-deploy-空城记与青铜剑.md](./fleet-4.0d-1-deploy-空城记与青铜剑.md) — 发版部署（Hermes 分机步骤）
- [laptop-fleet-3.1-display-name-via-agent.md](./laptop-fleet-3.1-display-name-via-agent.md) — 命名；Tier 0 默认 Hermes §三
- [fleet-4.0-job-workflow.md](./fleet-4.0-job-workflow.md) — Job 工程摘要
