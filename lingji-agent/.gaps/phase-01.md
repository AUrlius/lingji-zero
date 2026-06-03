# Phase 1 缺口记录

**日期**: 2026-05-31
**阶段**: 协议定义对齐（Go ↔ Python JSON 互通验证）

## 验证结果

| 检查项 | 结果 |
|--------|------|
| Go protocol/message.go 与 Python protocol.py 字段对齐 | ✅ 5 字段精确匹配 |
| Go 单元测试 | ✅ 8/8 passed |
| Go 解析 Python JSON | ✅ interop-test-001 全字段匹配 |
| Python 解析 Go JSON | ✅ go-interop-001 全字段匹配 |
| 6 种消息类型 | ✅ 两端枚举值一致 |

## 协议契约（已锁定）

```
Message {
    msg_id:    string          // UUID v4
    msg_type:  MsgType         // AUTH_REQ|HEARTBEAT|CMD_TEXT|HITL_REQ|HITL_RES|AGENT_RES
    device_id: string          // 设备标识
    timestamp: float64         // Unix 秒（Python time.time() / Go UnixMilli/1000）
    payload:   map[string]any  // 消息载荷
}
```

### 关键对齐细节

- **JSON key**: 全部 snake_case（Pydantic 默认 → Go json tag 显式指定）
- **timestamp 精度**: Python `time.time()` 返回秒级浮点，Go `UnixMilli()/1000` 对齐
- **payload 空值**: 两端默认初始化为 `{}`（非 null）
- **GOPROXY**: 已验证 `goproxy.cn` 可用，后续 Go 依赖拉取统一走此代理

---

## GAP-002 状态更新

**原描述**: gorilla/websocket 依赖从 go.dev 拉取可能被墙

**Phase 1 发现**: `GOPROXY=https://goproxy.cn,direct` 成功拉取 `github.com/google/uuid`。gorilla/websocket 大概率同理。Phase 2 将首次拉取验证。

**级别**: ⚠️ 中 → 🟢 低（已有可行方案，待 Phase 2 确认）

---

## 新缺口

无。本阶段无新缺口。
