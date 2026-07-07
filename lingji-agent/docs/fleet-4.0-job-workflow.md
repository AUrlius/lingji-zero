# Fleet 4.0 — Job Workflow (Engineering Summary)

> **Status**: **4.0a implemented** (2026-07-08) — Job store + `/v1/jobs` + fleet transfer linkage + Agent `job_tools` / `fleet_send_file` LJ-*  
> **Full spec**: [Sprint Fleet 4.0 — Job 工作流、调度层与分级验收](../../../../docs/sprints/第六阶段：编码实现与测试/Sprint Fleet 4.0 — Job 工作流、调度层与分级验收.md)

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

## HTTP API (planned)

```
POST   /v1/jobs
GET    /v1/jobs/{job_id}
GET    /v1/jobs?user_id=
POST   /v1/jobs/{job_id}/steps/{step_id}/report
```

Extend existing:

```
POST /v1/fleet/transfer  + job_id, step_id
FLEET_ACK                → update job step S4
```

## Scheduler tools (planned)

- `job_create`, `job_get`, `job_dispatch_step`, `job_close`
- `job_invoke_hermes` (Phase 4.0c)

Default scheduler: `lingji-pc` (青铜剑).

## User reply templates

```
LJ-A1B2C3D4 已完成。空城记 → 青铜剑：report.pdf 已保存至 ~/Downloads/LingjiIncoming/。
LJ-A1B2C3D4 失败：接收机未确认（…）。详情 GET /v1/jobs/LJ-A1B2C3D4
```

## Implementation phases

| Phase | Scope |
|-------|--------|
| **4.0a** | Job store + transfer linkage + scheduler tools + L1 close message |
| **4.0b** | JOB_DELEGATE/EVENT, receive_verify, Web job drawer |
| **4.0c** | Hermes bridge + playbooks |

## Existing code anchors

| Today | Fleet 4.0 wraps |
|-------|-----------------|
| `handler/fleet.go` `transfer_id`, `HandleAck` | S3/S4 evidence |
| `store/files_registry.go` `LF-*` | S2/S5 evidence |
| `fleet_tools.py` `fleet_send_file` | should attach `job_id` |
| `main.py` HITL `task_id` | L3 only |

## Related ops doc

Fleet 3.1 naming: prefer **Hermes §三** over browser Agent §二 — see [laptop-fleet-3.1-display-name-via-agent.md](./laptop-fleet-3.1-display-name-via-agent.md).
