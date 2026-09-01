# Fleet 4.0 — Job Workflow (Engineering Summary)

> **Status**: **4.0a implemented** (2026-07-08) · **4.0d-2 秘书台 MVP** (2026-08-31) · **4.0d-3 调度代批 HITL coded** (2026-09-01) · **Web v0.1.18 机要栏空态** (2026-09-02)；Hermes 入站 / `job_invoke_hermes` / 4.0d-4 **未做**  
> **Full spec**: [Sprint Fleet 4.0 — Job 工作流、调度层与分级验收](../../../../docs/sprints/第六阶段：编码实现与测试/Sprint Fleet 4.0 — Job 工作流、调度层与分级验收.md)  
> **4.0d spec**: [fleet-4.0d-remote-guardian-design.md](./fleet-4.0d-remote-guardian-design.md)  
> **Runbook**: [fleet-4.0d-remote-guardian-runbook.md](./fleet-4.0d-remote-guardian-runbook.md)  
> **Deploy**: [fleet-4.0d-1-deploy-空城记与青铜剑.md](./fleet-4.0d-1-deploy-空城记与青铜剑.md)

## One-line goal

User assigns **one intent** → **scheduler Agent** creates **`LJ-*` job** → **executors** (Hermes / PC Agents) run **`LJ-*-S*` steps** → **Gateway** is source of truth → user gets **`LJ-xxx 已完成`**.

## ID levels

| Level | Example | Owner |
|-------|---------|-------|
| L1 job | `LJ-A1B2C3D4` | Gateway mint |
| L2 step | `LJ-A1B2C3D4-S4` | Gateway on plan |
| L3 HITL | tool call id | LangGraph (do not confuse with L1) |

## Verification (dual layer)

1. **Machine (required)**: `FLEET_ACK` + `transfer_id` + optional `LF-*` holder change.  
2. **Agent verify (optional)**: structured `receive_verify` step with `evidence` checked against (1).

No pure chat «收到了吗» / «是的».

## File transfer steps (playbook `fleet.file_transfer`)

```
S1 resolve_targets   → scheduler
S2 locate_and_upload → sender agent/hermes
S3 relay_deliver     → gateway + sender (existing /v1/fleet/transfer)
S4 receive_machine   → FLEET_ACK (existing handler/fleet.go)
S5 receive_verify    → receiver agent (optional)
```

L1 `completed` iff all mandatory L2 steps `completed`.

## HTTP API

```
POST   /v1/jobs
GET    /v1/jobs/{job_id}
GET    /v1/jobs?user_id=
POST   /v1/jobs/{job_id}/dispatch
POST   /v1/jobs/{job_id}/steps/{step_id}/report
```

Extend existing:

```
POST /v1/fleet/transfer  + job_id, step_id
FLEET_ACK                → update job step S4
```

## Scheduler tools

- `job_get`、`job_create_fleet_transfer`、**`job_invoke`**（档 A：建 LJ-* + dispatch playbook）
- `hitl_list_pending`、`hitl_delegate_respond`（4.0d-3 兜底；主路径为空城记 HITL_REQ 硬代批）
- `job_invoke_hermes`（档 B，未做）

Default scheduler: **`lingji-laptop`（空城记）** when user is mobile; **`lingji-pc`（青铜剑）** when co-located. See 4.0d.

Guardian executor (Shanghai): **`lingji-pc`（青铜剑）** — not the user's chat target.

## User reply templates

```
LJ-A1B2C3D4 已完成。空城记 → 青铜剑：report.pdf 已保存至 ~/Downloads/LingjiIncoming/。
LJ-A1B2C3D4 失败：接收机未确认（…）。详情 GET /v1/jobs/LJ-A1B2C3D4
```

## Implementation phases

| Phase | Scope |
|-------|--------|
| **4.0a** | Job store + transfer linkage + scheduler tools + L1 close message |
| **4.0a-fix** | Upload fast-path: text with action intent → Agent not local save |
| **4.0b** | JOB_DELEGATE/EVENT, receive_verify, Web job drawer |
| **4.0c** | Hermes bridge + playbooks |
| **4.0d-1** | Web default `lingji-laptop` + `scheduler` config + Job `scheduler_agent_id` | ✅ coded |
| **4.0d-2** | `approval_scope` + 档 A playbooks + `JOB_DELEGATE` + Web 办公桌 | ✅ coded |
| **4.0d-3** | Delegated HITL（范围内空城记代批，敏感升级用户 dock） | ✅ coded |
| **4.0d-4** | Hermes Permission Proxy | 未做 |

## Existing code anchors

| Today | Fleet 4.0 wraps |
|-------|-----------------|
| `handler/fleet.go` `transfer_id`, `HandleAck` | S3/S4 evidence |
| `store/files_registry.go` `LF-*` | S2/S5 evidence |
| `fleet_tools.py` `fleet_send_file` | should attach `job_id` |
| `main.py` HITL `task_id` | L3 only |

## Related ops doc

Fleet 3.1 naming: prefer **Hermes §三** over browser Agent §二 — see [laptop-fleet-3.1-display-name-via-agent.md](./laptop-fleet-3.1-display-name-via-agent.md).
