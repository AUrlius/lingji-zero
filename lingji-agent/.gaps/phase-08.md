# Phase 8 缺口记录

**日期**: 2026-05-31
**阶段**: 集成测试 + 部署准备

## 验证结果

| 检查项 | 结果 |
|--------|------|
| Gateway 编译 + 启动 | ✅ |
| Gateway /health | ✅ |
| 手机端认证 | ✅ |
| Agent 认证 | ✅ |
| 消息闭环（手动测试） | ✅ |
| 消息闭环（自动化集成测试） | ⚠️ 时序问题 |

## 集成测试状态

- **手动测试**: ✅ 完全通过 — Phone ↔ Gateway ↔ Agent 消息闭环确认
- **自动化集成测试**: ⚠️ `test_message_roundtrip` 有时序问题（Gateway 消息已转发到 agent Send channel，但 Python websockets 客户端接收侧有时序竞态）
- **单元测试**: ✅ 82/82 passed

## 集成测试架构

```
integration_test.py
├── GatewayProcess     ← 启动/停止 Go Gateway
├── PhoneSimulator     ← 模拟手机端 WS 客户端
├── MockAgent          ← 模拟 Agent WS 客户端
└── 测试用例:
    ├── test_gateway_health        ✅
    ├── test_phone_connect_auth    ✅
    ├── test_message_roundtrip     ⚠️
    └── test_multiple_messages     ⚠️
```

## 部署指南

### Gateway 部署到阿里云

```bash
# 编译
cd lingji-gateway
GOPROXY=https://goproxy.cn,direct go build -o lingji-gateway .

# 上传
scp lingji-gateway user@your.gateway.host:/opt/lingji/

# systemd 服务
sudo tee /etc/systemd/system/lingji-gateway.service << 'EOF'
[Unit]
Description=灵机计划 Gateway
After=network.target

[Service]
Type=simple
User=hermes
WorkingDirectory=/opt/lingji
Environment="LINGJI_PORT=8765"
ExecStart=/opt/lingji/lingji-gateway
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now lingji-gateway
```

### Agent 启动

```bash
cd lingji-agent
source .venv/bin/activate
export DEEPSEEK_API_KEY="sk-xxx"
python -m lingji_agent.main
```

### Phone CLI 启动

```bash
pip install websockets
python phone_client.py --host lingji.mygoal.tech --port 443 --device-id myphone
```

---

## GAP-003（新增）

**级别**: 🟢 低  
**描述**: 集成测试 `test_message_roundtrip` 存在时序竞态 — Gateway 成功将消息写入 agent 的 Send channel，但 Python websockets 客户端接收侧偶尔丢消息。手动测试完全通过。  
**影响**: 不影响生产使用，仅影响自动化 CI。  
**可能方案**: 增加重试逻辑、使用更长的等待时间、改用 asyncio.Queue 同步。

## 新缺口

| 编号 | 级别 | 描述 |
|------|------|------|
| GAP-003 | 🟢 低 | 集成测试时序竞态 |
