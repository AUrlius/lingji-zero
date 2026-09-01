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

## E. 离沪主路径验收（6 小考 + 联考）

默认 `https://lingji.mygoal.tech`（Ctrl+F5），对象是**空城记**。任一步不过就停，记下题号。

**① 检查上海（无 HITL）**  
对秘书：「检查上海 Agent 状态。」  
过：侧栏出现 `LJ-*` 并结案；顶部**没有**「需您授权」。

**② 发给青铜剑**  
上传一个小文件，同一条消息写：「把这个文件发到上海青铜剑。」  
过：工单结案；青铜剑 Incoming 有文件。

**③ 纯上传（必须先点「新交办」）**  
只上传、输入框留空发送。  
过：提示已保存到电脑（空城记）；**不要**出现发给青铜剑的工单。  
勿在②的同一条交办里再空传，否则会当成续传、不走本机保存。

**④ 无 Job 时仍要你批**  
确认侧栏没有「进行中」。打开 `?debug=1`，对象改成**青铜剑**：「执行 `uname -a`。」  
过：出现「需您授权」→ 点**拒绝**。

**⑤ 范围内代批**  
回到默认办公桌（空城记）：「跑一下 fleet-smoke。」侧栏还是**进行中**时，马上 `?debug=1` 对青铜剑：「执行 `uname -a`。」  
过：**没有**授权条，命令能继续。若工单已结案再发，会变成④，重来。

**⑥ 敏感升级**  
在同一条仍进行中的工单下（或再让秘书派一条），debug 对青铜剑：「删除 `~/.ssh/id_rsa`。」  
过：授权条出现 → **务必拒绝**。

**联考：** ①→②→③→④→⑤→⑥ 按顺序连做，中间不要拖太久。秘书不会替你点授权条，也不会自己切 debug。

---

## F. Break-glass（仅调度与 Gateway 均不可用）

用户可直接让 **Hermes @ 青铜剑** 执行 §A/C 命令；**不计入** Job 台账，事后补记运维日志。

---

## G. 相关文档

- [fleet-4.0d-1-deploy-空城记与青铜剑.md](./fleet-4.0d-1-deploy-空城记与青铜剑.md) — 发版部署（Hermes 分机步骤）
- [laptop-fleet-3.1-display-name-via-agent.md](./laptop-fleet-3.1-display-name-via-agent.md) — 命名；Tier 0 默认 Hermes §三
- [fleet-4.0-job-workflow.md](./fleet-4.0-job-workflow.md) — Job 工程摘要
