# Phase 2 缺口记录

**日期**: 2026-05-31
**阶段**: Go Gateway WebSocket Hub（连接池管理 + 消息路由 + 离线队列）

## 验证结果

| 检查项 | 结果 |
|--------|------|
| gorilla/websocket v1.5.3 拉取 | ✅ goproxy.cn 可用（GAP-002 确认解决） |
| `go build` | ✅ 编译通过 |
| Hub 单元测试 | ✅ 7/7 passed |
| Queue 单元测试 | ✅ 4/4 passed |
| Protocol 测试 | ✅ 10/10 passed |
| **全量** | ✅ **21/21 passed** |

## 实现组件

### Hub (hub/hub.go)
- 连接池：`map[deviceID]*Client`，Register/Unregister 通道模式
- 重复设备踢出：同 deviceID 新连接自动关闭旧连接
- 心跳检查：定时扫描，超时踢出僵尸连接
- 消息转发：SendToDevice / BroadcastToAll / ForwardMessage
- 优雅退出：stopOnce 幂等 + done channel 同步

### WS Handler (handler/ws.go)
- WebSocket 升级：gorilla/websocket Upgrader
- 鉴权：Authorization header Bearer token
- AUTH_REQ 处理：首次连接后更新 deviceID
- 消息路由：CMD_TEXT → PC, AGENT_RES → 广播, HITL_REQ → 广播, HITL_RES → PC
- 离线投递：设备上线时自动投递缓存消息

### 离线队列 (queue/offline.go)
- 环形缓冲区：固定大小，满时覆盖最旧消息
- 按设备隔离：每个 deviceID 独立队列
- DequeueAll：取走即清空

### 主入口 (main.go)
- 组装 Hub + Queue + Handler
- /ws 端点 + /health 健康检查
- 优雅退出：SIGINT/SIGTERM

## 本阶段调试发现的 Bug（已修复）

| Bug | 根因 | 修复 |
|-----|------|------|
| Hub 测试死锁 | `h.mu.Lock()` 内调 `h.Len()` → `h.mu.RLock()` → Go RWMutex 不可重入 | 持锁时直接用 `len(h.clients)` |
| Hub Stop panic | Conn=nil 时 `c.Conn.Close()` | nil 检查 |
| 双重 Stop panic | `close(stopCh)` 两次 | sync.Once 幂等 |
| 心跳踢出死锁 | `h.Unregister()` 在 Run select 内同步调用 → channel 阻塞 | `go h.Unregister()` 异步 |

---

## GAP-002 最终状态

**结论**: ✅ 已解决。`GOPROXY=https://goproxy.cn,direct` 成功拉取 google/uuid + gorilla/websocket。

---

## 新缺口

无。
