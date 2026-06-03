# Phase 6 缺口记录

**日期**: 2026-05-31
**阶段**: 执行层（NativeSandbox + HITL 集成 + 工具完善）

## 验证结果

| 检查项 | 结果 |
|--------|------|
| NativeSandbox subprocess 执行 | ✅ echo/ls/pwd 通过 |
| 路径白名单/黑名单 | ✅ /home /tmp 放行，/etc /sys 拦截 |
| 命令白名单 | ✅ ls/cat 放行，nmap 拦截 |
| 超时控制 | ✅ python3 sleep 60 → 1s 超时 |
| HITL 拦截 CRITICAL 工具 | ✅ delete_file/execute_command 被拦截 |
| HITL 关闭时正常执行 | ✅ _hitl_enabled=False 直接执行 |
| Docker 检测修正 | ✅ 真正尝试 docker info 而非仅 which |
| **pytest 全量** | ✅ **82/82 passed** |

## 测试分布

| 模块 | 新增 |
|------|------|
| sandbox | 17 (路径7 + 命令3 + 执行6 + 创建1) |
| hitl | 3 (safe执行 + critical拦截 + 关闭开关) |
| **累计** | **82** |

## 实现详情

### sandbox.py — 三层架构

```
BaseSandbox (ABC)
├── NativeSandbox    ← subprocess + 安全策略（当前使用）
└── DockerSandbox    ← 容器隔离（GAP-001 解决后可用）
```

**安全策略**:
- 路径白名单: /home, /tmp, /mnt, /var/tmp, /dev/null
- 路径黑名单: /etc/passwd, /sys, /proc, /boot, /root
- 命令白名单: 30+ 安全命令（ls/cat/echo/curl/git 等）
- 超时: asyncio.wait_for 强制截断
- 环境变量: 清理 LD_PRELOAD/LD_LIBRARY_PATH

### 工具清单（7 个）

| 工具 | 风险 | 功能 |
|------|------|------|
| list_directory | 🟢 SAFE | 列出目录内容 |
| read_file | 🟢 SAFE | 读取文件（限 100KB） |
| search_files | 🟢 SAFE | 按模式搜索文件 |
| move_file | 🟡 WARN | 移动/重命名 |
| delete_file | 🔴 CRITICAL | 删除文件（HITL 拦截） |
| system_status | 🟢 SAFE | CPU/内存/磁盘 |
| get_processes | 🟢 SAFE | 进程列表 Top10 |
| execute_command | 🔴 CRITICAL | 沙箱执行命令（HITL 拦截） |

### HITL 集成

```
tool_executor:
  if risk == CRITICAL and hitl_enabled:
      → 返回 {"hitl_required": True, "error": "需要手机端审批"}
  else:
      → 正常执行
```

### Docker 检测修正

之前 `shutil.which("docker")` 找到 Windows 的 docker.exe 但无法在 WSL2 运行。
修正为 `subprocess.run(["docker", "info"])` 真实验证可用性。

---

## GAP-001 状态

Docker Desktop 已安装在 Windows，但 WSL2 集成未启用。
`DockerSandbox.is_available()` 现在正确返回 False。
用户启用 WSL2 Integration 后自动切换。

## 新缺口

无。
