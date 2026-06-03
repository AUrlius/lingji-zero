# Phase 0 缺口记录

**日期**: 2026-05-31  
**阶段**: 项目初始化（Go Gateway + Python Agent + Phone CLI 骨架）

## 验证结果

| 检查项 | 结果 |
|--------|------|
| Go 1.23.4 安装 | ✅ 用户态安装到 ~/.local/go |
| `go build` | ✅ 7.2MB 二进制编译成功 |
| Python 3.12 venv | ✅ 创建成功 |
| pip install 全部依赖 | ✅ websockets/pydantic/langgraph/openai 等 |
| Python 全部 import | ✅ 17 个模块导入通过 |
| pytest | ✅ 7/7 tests passed |
| Docker | ❌ 未安装 |

---

## GAP-001: Docker 未安装

**级别**: ⚠️ 中（Phase 0-5 不阻塞，Phase 6 必须解决）

**描述**: WSL2 环境需要 Windows 侧安装 Docker Desktop 并启用 WSL2 集成。当前 `docker` 命令不存在。

**影响**: Phase 6（执行层 Docker 沙箱）无法开始。

**可能方案**:
1. Windows 安装 Docker Desktop → 启用 WSL2 Integration
2. 阿里云服务器已安装 Docker → 沙箱在远端执行（增加网络延迟，但可行）
3. 降级为 subprocess + seccomp（背离 v3 设计决策）

**预计解决阶段**: Phase 5 之前

---

## GAP-001 解决记录

**日期**: 2026-06-01
**实际根因**: WSL2 集成配置一直正确，但 Docker Desktop 未登录/未运行导致 `/usr/bin/docker` symlink 不存在
**解决方案**: 登录 Docker Desktop → WSL 中 docker CLI 自动可用（symlink 由 Docker Desktop 启动时创建）
**验证**: `docker --version` → Docker 29.3.1, `docker run --rm hello-world` 成功
**后续**: DockerSandbox.execute() 已实现（commit: 4d72f50），105 tests passing

---

## GAP-002: gorilla/websocket 依赖拉取

**级别**: ⚠️ 中（Phase 1 不阻塞，Phase 2 必须解决）

**描述**: Go Gateway Phase 2 需要 `github.com/gorilla/websocket` 实现 WebSocket 升级。`go get` 默认从 proxy.golang.org 拉取，国内可能超时。

**影响**: Phase 2 Gateway 核心功能无法编译。

**可能方案**:
1. 设置 `GOPROXY=https://goproxy.cn` 使用七牛代理
2. 手动 vendor 依赖
3. 用 `nhooyr.io/websocket` 替代（更现代，但生态不如 gorilla）

**预计解决阶段**: Phase 2 开始前
