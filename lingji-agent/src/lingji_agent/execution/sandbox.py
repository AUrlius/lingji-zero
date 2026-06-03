"""沙箱执行引擎（Sprint 3）

BaseSandbox(ABC) → NativeSandbox(subprocess+安全策略) | DockerSandbox(预留)

安全策略：
  - 路径白名单：仅允许 /home, /tmp, /mnt 下的操作
  - 路径黑名单：禁止 /etc, /sys, /proc, /boot, /root
  - 命令白名单：仅允许安全命令
  - 超时控制：asyncio.wait_for
"""

import asyncio
import contextlib
import contextvars
import logging
import os
import shlex
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

_force_docker_sandbox: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "lingji_force_docker_sandbox", default=False
)


def get_force_docker_sandbox() -> bool:
    """当前上下文是否要求 CRITICAL 工具强制 Docker 隔离（专利 5 联动）。"""
    return _force_docker_sandbox.get()


def set_force_docker_sandbox(value: bool) -> contextvars.Token[bool]:
    return _force_docker_sandbox.set(value)


def reset_force_docker_sandbox(token: contextvars.Token[bool]) -> None:
    _force_docker_sandbox.reset(token)


@contextlib.contextmanager
def sandbox_execution_context(force_docker: bool = False) -> Iterator[None]:
    """在 CRITICAL 工具执行期间临时设置沙箱隔离策略。"""
    if not force_docker:
        yield
        return
    token = set_force_docker_sandbox(True)
    try:
        yield
    finally:
        reset_force_docker_sandbox(token)


# ── 数据模型 ──────────────────────────────────────────────

@dataclass
class MountPoint:
    host: str
    container: str
    mode: str = "ro"


@dataclass
class ResourceLimits:
    cpu_quota: float = 1.0
    memory_mb: int = 256
    timeout_sec: int = 30


@dataclass
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False


# ── 抽象接口 ──────────────────────────────────────────────

class BaseSandbox(ABC):
    """沙箱抽象接口"""

    @abstractmethod
    async def execute(
        self,
        command: str | list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        limits: ResourceLimits | None = None,
    ) -> ExecutionResult:
        ...

    @abstractmethod
    def is_available(self) -> bool:
        ...


# ── 安全策略 ──────────────────────────────────────────────

PATH_ALLOWLIST = [
    "/home",
    "/tmp",
    "/mnt",
    "/var/tmp",
    "/dev/null",
]

PATH_BLOCKLIST = [
    "/etc/passwd",
    "/etc/shadow",
    "/etc/sudoers",
    "/etc/ssh",
    "/sys",
    "/proc",
    "/boot",
    "/root",
    "/.ssh",
    "~/.ssh",
]

COMMAND_ALLOWLIST = {
    "ls", "cat", "head", "tail", "wc", "find", "grep", "stat",
    "echo", "date", "whoami", "hostname", "uname", "pwd", "id",
    "df", "du", "free", "uptime", "ps", "top",
    "python3", "python", "pip", "pip3",
    "curl", "wget",
    "mkdir", "cp", "mv", "rm", "touch", "chmod", "chown",
    "tar", "gzip", "gunzip", "zip", "unzip",
    "git",
}


def validate_path(path_str: str) -> bool:
    """检查路径是否安全"""
    path = Path(os.path.expanduser(path_str)).resolve()
    path_s = str(path)

    # 黑名单检查
    for blocked in PATH_BLOCKLIST:
        blocked_expanded = os.path.expanduser(blocked)
        if path_s.startswith(blocked_expanded) or path_s == blocked_expanded:
            logger.warning("[Sandbox] 路径被黑名单拦截: %s", path_s)
            return False

    # 白名单检查
    for allowed in PATH_ALLOWLIST:
        allowed_expanded = os.path.expanduser(allowed)
        if path_s.startswith(allowed_expanded) or path_s == allowed_expanded:
            return True

    logger.warning("[Sandbox] 路径不在白名单: %s", path_s)
    return False


def validate_command(cmd: list[str]) -> tuple[bool, str]:
    """检查命令是否在允许列表中"""
    if not cmd:
        return False, "空命令"
    base = os.path.basename(cmd[0])
    if base not in COMMAND_ALLOWLIST:
        return False, f"命令不在白名单: {base}"
    return True, ""


# ── NativeSandbox 实现 ────────────────────────────────────

class NativeSandbox(BaseSandbox):
    """基于 subprocess 的本地沙箱（安全策略限制）"""

    def __init__(self, limits: ResourceLimits | None = None):
        self.default_limits = limits or ResourceLimits()

    def is_available(self) -> bool:
        return True  # subprocess 始终可用

    async def execute(
        self,
        command: str | list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        limits: ResourceLimits | None = None,
    ) -> ExecutionResult:
        """执行命令（带安全检查）"""
        limits = limits or self.default_limits

        # 解析命令
        if isinstance(command, str):
            cmd_parts = shlex.split(command)
        else:
            cmd_parts = list(command)

        # 命令白名单检查
        ok, reason = validate_command(cmd_parts)
        if not ok:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"安全检查失败: {reason}",
                duration_ms=0,
            )

        # 路径安全检查（对 cp/mv/rm 等参数中的路径）
        for arg in cmd_parts[1:]:
            if arg.startswith("-"):
                continue
            if "/" in arg and not arg.startswith("http"):
                if not validate_path(arg):
                    return ExecutionResult(
                        exit_code=-1,
                        stdout="",
                        stderr=f"安全检查失败: 路径 {arg} 不在白名单",
                        duration_ms=0,
                    )

        # cwd 检查
        if cwd and not validate_path(cwd):
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"安全检查失败: 工作目录 {cwd} 不在白名单",
                duration_ms=0,
            )

        # 构建环境变量
        safe_env = os.environ.copy()
        if env:
            safe_env.update(env)
        # 清理危险环境变量
        safe_env.pop("LD_PRELOAD", None)
        safe_env.pop("LD_LIBRARY_PATH", None)

        logger.info("[Sandbox] 执行: %s (cwd=%s, timeout=%ds)", 
                     " ".join(cmd_parts), cwd or ".", limits.timeout_sec)

        start = time.monotonic()
        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *cmd_parts,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=safe_env,
                ),
                timeout=limits.timeout_sec,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=limits.timeout_sec,
            )

            duration = (time.monotonic() - start) * 1000
            return ExecutionResult(
                exit_code=proc.returncode or 0,
                stdout=stdout.decode("utf-8", errors="replace")[:10000],  # 截断
                stderr=stderr.decode("utf-8", errors="replace")[:5000],
                duration_ms=duration,
            )

        except asyncio.TimeoutError:
            duration = (time.monotonic() - start) * 1000
            logger.warning("[Sandbox] 命令超时: %s", " ".join(cmd_parts))
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"命令执行超时（{limits.timeout_sec}秒）",
                duration_ms=duration,
                timed_out=True,
            )
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            logger.error("[Sandbox] 执行失败: %s", e)
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_ms=duration,
            )


# ── DockerSandbox（预留）───────────────────────────────────

class DockerSandbox(BaseSandbox):
    """基于 Docker 的隔离执行环境（GAP-001 解决后可用）"""

    def __init__(self, image: str = "python:3.11-slim"):
        self.image = image

    def is_available(self) -> bool:
        import shutil
        if shutil.which("docker") is None:
            return False
        # 确认 Docker 在 WSL2 中真正可用
        import subprocess
        try:
            result = subprocess.run(
                ["docker", "info"], capture_output=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    async def execute(
        self,
        command: str | list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        limits: ResourceLimits | None = None,
    ) -> ExecutionResult:
        """在 Docker 容器中隔离执行命令"""
        limits = limits or ResourceLimits()

        if isinstance(command, str):
            cmd_parts = shlex.split(command)
        else:
            cmd_parts = list(command)

        if not cmd_parts:
            return ExecutionResult(exit_code=-1, stdout="", stderr="空命令", duration_ms=0)

        workdir = cwd or os.getcwd()
        docker_args = [
            "docker", "run", "--rm", "-i",
            "--network=none",
            f"--memory={limits.memory_mb}m",
            f"--cpus={limits.cpu_quota}",
            f"--memory-swap={limits.memory_mb}m",
            "--pids-limit=128",
            "-v", f"{workdir}:/workspace:ro",
            "-w", "/workspace",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
        ]

        if env:
            for k, v in env.items():
                docker_args.extend(["-e", f"{k}={v}"])

        docker_args.append(self.image)
        docker_args.extend(cmd_parts)

        start = time.monotonic()
        logger.info("[DockerSandbox] %s (mem=%dm, timeout=%ds)",
                     " ".join(cmd_parts), limits.memory_mb, limits.timeout_sec)

        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *docker_args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=limits.timeout_sec + 10,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=limits.timeout_sec,
            )

            duration = (time.monotonic() - start) * 1000
            return ExecutionResult(
                exit_code=proc.returncode or 0,
                stdout=stdout.decode("utf-8", errors="replace")[:10000],
                stderr=stderr.decode("utf-8", errors="replace")[:5000],
                duration_ms=duration,
            )

        except asyncio.TimeoutError:
            duration = (time.monotonic() - start) * 1000
            logger.warning("[DockerSandbox] 超时: %s", " ".join(cmd_parts))
            return ExecutionResult(
                exit_code=-1, stdout="",
                stderr=f"命令执行超时（{limits.timeout_sec}秒）",
                duration_ms=duration, timed_out=True,
            )
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            logger.error("[DockerSandbox] 失败: %s", e)
            return ExecutionResult(
                exit_code=-1, stdout="", stderr=str(e), duration_ms=duration,
            )


class FailClosedSandbox(BaseSandbox):
    """威胁升级要求 Docker，但 Docker 不可用 — 拒绝 Native 回退。"""

    def is_available(self) -> bool:
        return False

    async def execute(
        self,
        command: str | list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        limits: ResourceLimits | None = None,
    ) -> ExecutionResult:
        return ExecutionResult(
            exit_code=-1,
            stdout="",
            stderr=(
                "威胁检测已触发隔离升级，但 Docker 不可用，"
                "拒绝在 Native 沙箱执行 CRITICAL 命令。"
            ),
            duration_ms=0,
        )


# ── Factory ───────────────────────────────────────────────

def create_sandbox(*, force_docker: bool | None = None) -> BaseSandbox:
    """自动选择可用沙箱。

    force_docker: 显式指定；为 None 时读取 sandbox_execution_context 上下文。
    威胁联动开启时，Docker 不可用则 FailClosed，不回退 Native。
    """
    require_docker = (
        force_docker if force_docker is not None else get_force_docker_sandbox()
    )
    docker = DockerSandbox()
    if require_docker:
        if docker.is_available():
            logger.warning(
                "[Sandbox] sanitizer 威胁升级：CRITICAL 工具强制 DockerSandbox"
            )
            return docker
        logger.error(
            "[Sandbox] 威胁升级要求 Docker，但 Docker 不可用 — FailClosed"
        )
        return FailClosedSandbox()
    if docker.is_available():
        logger.info("[Sandbox] 使用 Docker 沙箱")
        return docker
    logger.info("[Sandbox] Docker 不可用，使用 NativeSandbox（subprocess + 安全策略）")
    return NativeSandbox()
