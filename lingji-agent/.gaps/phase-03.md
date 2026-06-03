# Phase 3 缺口记录

**日期**: 2026-05-31
**阶段**: PC 基础层（配置加载 + 数据库 + WS 客户端 + 启动序列）

## 验证结果

| 检查项 | 结果 |
|--------|------|
| Python import 全部通过 | ✅ |
| config.py YAML 加载 + 环境变量覆盖 | ✅ 3 级优先级 |
| db.py SQLite 3 表 DDL + CRUD | ✅ 幂等 |
| ws_client.py AUTH 握手 + 心跳 + 路由分派 + 指数退避重连 | ✅ |
| main.py 完整启动序列 | ✅ |
| **pytest 全量** | ✅ **29/29 passed** |

## 测试分布

| 模块 | 测试数 |
|------|--------|
| config | 9 |
| db | 4 |
| protocol | 3 |
| registry | 4 |
| ws_client | 9 |
| **合计** | **29** |

## 实现详情

### config.py
- `load_config()`: 默认值 → YAML文件 → 环境变量（3级优先级）
- `_ENV_MAP`: 8个环境变量映射（LINGJI_*, DEEPSEEK_API_KEY 等）
- 自动查找 `config/default_config.yaml`

### ws_client.py
- 连接: `websockets.connect()` + Authorization header
- 握手: 连接成功后自动发送 AUTH_REQ
- 心跳: 15s 间隔 HEARTBEAT
- 路由: 收到的消息 → `Router.dispatch()`
- 重连: 指数退避 1s→2s→4s→...→60s
- 回调: `on_connected()` 注册连接成功回调

### main.py
```
启动序列:
  1. load_config()       → 配置
  2. setup_logging()     → structlog
  3. init_db()           → SQLite
  4. Router()            → 消息路由（注册 AGENT_RES 处理器）
  5. GatewayClient()     → WS 连接 + 心跳
  6. 等待 KeyboardInterrupt → 优雅退出
```

---

## 新缺口

无。
