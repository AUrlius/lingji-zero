# 灵机 Web 客户端目录（G6.4）

建站 AI / 主程对齐用。Handoff：**[中文](../../../docs/internal/2026-06-03-灵机Web前端设计稿-建站AI交付说明.md)** · **[English (Builder AI)](../../../docs/internal/2026-06-03-Lingji-Web-Frontend-Builder-AI-Handoff-EN.md)**。协议速查见 [`2026-06-03-前端对齐建站AI规格.md`](../../../docs/internal/2026-06-03-前端对齐建站AI规格.md)。

## 目录树

```text
web/
  index.html       # 布局、引用 css/js
  css/app.css      # ChatGPT 式深色壳
  js/ui.js         # window.LingjiUI — 纯 DOM
  js/lingji-api.js # window.LingjiChat — WS / Files / 会话
  STRUCTURE.md     # 本文件
```

## DOM id 清单

| id | 元素 |
|----|------|
| `sidebarOverlay` | 侧栏遮罩 |
| `sidebar` | 侧栏容器 |
| `btnNewChat` | 新对话按钮 |
| `sessionList` | 会话列表 |
| `status` | 连接状态 |
| `settings` | 调试面板 |
| `gwHost`, `gwPort` | Gateway 地址 |
| `chat` | 消息流 |
| `pendingBar` | 待上传 chip |
| `fileInput` | 隐藏 file input |
| `input` | 文本输入 |
| `btnSend` | 发送 |

## 事件流

```text
pageshow → LingjiChat.init()
  → connect() → AUTH_REQ
  → AGENT_RES connected → CMD_LIST_SESSIONS（强制同步，sessionStorage 仅离线缓存）
  → client_id：同 token → user-{hash}（Fleet 第一期）
  → conn-* + user_id payload（Fleet 1.5 多端同时在线）

btnNewChat → startNewSession()
session-item → switchSession(thread_id)
btnSend / Enter → send() → POST /files? → CMD_TEXT
HITL 按钮 → HITL_RES
```
