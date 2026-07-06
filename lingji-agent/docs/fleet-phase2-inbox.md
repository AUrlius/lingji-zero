# Fleet Phase 2 — Gateway Inbox（设计摘要）

> 状态：MVP 已实现（2026-07-06），待生产部署  
> 关联：[灵机Fleet连通实施计划](../../../../docs/internal/灵机Fleet连通实施计划.md)

## 目标

手机 / 任一端 Web 在侧栏看到**同一 `user_id` 下、多台 Agent 的会话索引**；点选会话时按 `agent_id` 路由并加载 Gateway 已落库的 transcript（Agent 仍负责完整 checkpoint 历史）。

## 架构

```
Web/Phone ──GET /v1/inbox/threads──► Gateway SQLite
         ──WS CMD_TEXT / AGENT_RES──► inbox_capture ──► SQLite
         ──CMD_LIST_SESSIONS────────► Agent ──AGENT_RES sessions──► capture + Web
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/inbox/threads?user_id=user-xxx&token=` | 跨 Agent 会话列表 |
| GET | `/v1/inbox/messages?thread_id=&agent_id=&token=` | 单会话 transcript（Gateway 落库部分） |

鉴权与 `/v1/agents` 相同：`Bearer` 或 `?token=`。

## 配置

| 环境变量 | 默认 | 说明 |
|----------|------|------|
| `LINGJI_INBOX_DB` | `data/inbox.db` | SQLite 路径（父目录须可写） |

## Web（v0.1.5）

- 连接后 `fetchInboxThreads()` 与 Agent `CMD_LIST_SESSIONS` 结果 `mergeInboxSessions()`
- 侧栏会话显示 `agent_id` 标签（Primary PC / Laptop）
- 切换会话时 `setSelectedAgentId` + `fetchInboxMessages` + `sendSessionSwitch`

## Agent 变更

- `list_chat_sessions` 响应每项增加 `agent_id`（`config.network.device_id`）
- 普通回复 `AGENT_RES` 增加 `thread_id` 字段

## 已知限制（MVP）

1. **历史会话**：Phase 2 部署前的对话不会自动出现在 inbox；需对各 Agent 发一次 `CMD_LIST_SESSIONS`（切换下拉即触发）以回填 `threads` 表。
2. **Transcript 完整度**：Gateway 仅保存 WS 经过的 user/agent 文本；完整历史仍以 Agent LangGraph checkpoint 为准（`session_switched` 时 Agent 仍会下发 `history`）。
3. **跨箱传文件**：第三期 `fleet_*`，本期不做。

## 部署检查清单

1. Gateway：`go build` 并部署；创建可写 `data/`；可选设置 `LINGJI_INBOX_DB`
2. 青铜剑 + 空城记 Agent：`git pull` 并重启
3. 浏览器：`https://lingji.mygoal.tech/?token=...` 强制刷新（`v=0.1.5`）
4. 验收：在 Laptop 发一条消息后，手机侧栏应出现带 **Laptop** 标签的会话项

## 测试

```bash
cd lingji-gateway && go test ./... -count=1
```
