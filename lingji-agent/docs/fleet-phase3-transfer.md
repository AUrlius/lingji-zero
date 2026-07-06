# Fleet Phase 3 — Cross-Agent File Relay

> Status: implemented (2026-07-06)  
> Related: [灵机Fleet连通实施计划](../../../../docs/internal/灵机Fleet连通实施计划.md)

## Goal

Any entry (phone / Web) can command a source Agent to send a file to another Agent's `incoming_dir`, or push attachments to the user's phone/Web. Gateway reuses G6 `/files` as the transit hop.

## Flow

```
User → CMD_TEXT (target_agent_id=source) → Source Agent LLM
  → fleet_send_file → POST /files → POST /v1/fleet/transfer
  → Gateway FLEET_DELIVER → Target Agent save_uploads_to_pc → FLEET_ACK
  → Gateway AGENT_RES fan-out + inbox capture
```

For `to_user_id`, Gateway skips target Agent and fans out `AGENT_RES` with `attachments[]` directly.

## HTTP API

| Method | Path | Auth |
|--------|------|------|
| POST | `/v1/fleet/transfer` | Bearer or `?token=` (same as `/files`) |

**Request body:**

```json
{
  "from_agent_id": "lingji-laptop",
  "to_agent_id": "lingji-pc",
  "to_user_id": "",
  "thread_id": "…",
  "user_id": "user-xxxxxxxx",
  "uploads": [
    {
      "file_id": "…",
      "name": "report.pdf",
      "download_path": "/files/…?token=…",
      "size_bytes": 1234,
      "mime": "application/pdf"
    }
  ]
}
```

Exactly one of `to_agent_id` or `to_user_id` is required.

**Response:**

```json
{ "transfer_id": "uuid", "status": "pending|queued|delivered", "to_agent_id": "…" }
```

## WebSocket

| Type | Direction | Purpose |
|------|-----------|---------|
| `FLEET_DELIVER` | Gateway → target Agent | `uploads[]` same schema as G6 |
| `FLEET_ACK` | target Agent → Gateway | `transfer_id`, `status`, `saved[]` / `error` |

## Agent

| Component | Path |
|-----------|------|
| Tool | `fleet_send_file` (`execution/tools/fleet_tools.py`) |
| HTTP client | `network/fleet_client.py` |
| Target delivery | `main.py` `on_fleet_deliver` → `save_uploads_to_pc` |

- Risk: `WARN` (same as `send_file_to_user`); sensitive paths soft-blocked.
- `user_id` / `thread_id` injected by orchestrator from the active CMD_TEXT context.

## Inbox

Gateway `CaptureFleetTransfer` writes a summary line on completion, e.g.:

`📁 Fleet: report.pdf lingji-laptop → lingji-pc 已保存`

## Acceptance (production)

1. Rebuild & deploy Gateway; restart both Agents (`lingji-pc`, `lingji-laptop`).
2. **Laptop → PC**: Phone selects Laptop, send「把 xxx.pdf 发到青铜剑」→ file appears in PC `~/Downloads/LingjiIncoming/`.
3. **Laptop → Phone**: Phone selects Laptop, send「把这个文件发给我」→ chat shows downloadable attachment.
4. Inbox on any entry shows the fleet transfer summary.

## Tests

```bash
cd lingji-gateway && go test ./... -count=1
cd lingji-agent && python3 -m pytest tests/test_fleet_tools.py -q
cd lingji-agent && python3 tests/integration_test.py   # includes fleet E2E
```
