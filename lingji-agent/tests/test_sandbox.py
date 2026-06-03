"""沙箱单元测试"""

import pytest

from lingji_agent.execution.sandbox import (
    NativeSandbox,
    DockerSandbox,
    create_sandbox,
    validate_path,
    validate_command,
    ResourceLimits,
    ExecutionResult,
)


class TestPathValidation:
    def test_allow_home(self):
        assert validate_path("/home/user") is True
        assert validate_path("/home") is True

    def test_allow_tmp(self):
        assert validate_path("/tmp/test") is True

    def test_block_etc(self):
        assert validate_path("/etc/passwd") is False
        assert validate_path("/etc/ssh") is False

    def test_block_sys(self):
        assert validate_path("/sys/class") is False

    def test_block_proc(self):
        assert validate_path("/proc/cpuinfo") is False

    def test_block_root(self):
        assert validate_path("/root/.bashrc") is False

    def test_expanduser(self):
        """~ 展开后检查"""
        # ~/ 展开后通常是 /home/user，应在白名单
        import os
        home = os.path.expanduser("~")
        assert validate_path(home) is True


class TestCommandValidation:
    def test_allow_safe_commands(self):
        for cmd in ["ls", "cat", "echo", "pwd", "date", "find", "grep"]:
            ok, reason = validate_command([cmd])
            assert ok, f"{cmd} should be allowed, got: {reason}"

    def test_block_dangerous_commands(self):
        for cmd in ["nmap", "nc", "tcpdump", "iptables"]:
            ok, _ = validate_command([cmd])
            assert not ok, f"{cmd} should be blocked"

    def test_empty_command(self):
        ok, reason = validate_command([])
        assert not ok


class TestNativeSandbox:
    @pytest.fixture
    def sandbox(self):
        return NativeSandbox()

    @pytest.mark.asyncio
    async def test_execute_echo(self, sandbox):
        result = await sandbox.execute(["echo", "hello world"])
        assert result.exit_code == 0
        assert "hello world" in result.stdout

    @pytest.mark.asyncio
    async def test_execute_ls(self, sandbox):
        result = await sandbox.execute(["ls", "/tmp"])
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_execute_blocked_command(self, sandbox):
        result = await sandbox.execute(["nmap", "-sP", "127.0.0.1"])
        assert result.exit_code == -1
        assert "白名单" in result.stderr

    @pytest.mark.asyncio
    async def test_execute_blocked_path(self, sandbox):
        """尝试读取 /etc/passwd 应被拦截"""
        result = await sandbox.execute(["cat", "/etc/passwd"])
        # 命令本身在白名单，但路径参数被拦截
        assert result.exit_code != 0 or "安全检查" in result.stderr

    @pytest.mark.asyncio
    async def test_execute_timeout(self, sandbox):
        result = await sandbox.execute(
            ["python3", "-c", "import time; time.sleep(60)"],
            limits=ResourceLimits(timeout_sec=1),
        )
        assert result.timed_out is True

    @pytest.mark.asyncio
    async def test_execute_with_cwd(self, sandbox):
        result = await sandbox.execute(["pwd"], cwd="/tmp")
        assert "/tmp" in result.stdout

    def test_is_available(self, sandbox):
        assert sandbox.is_available() is True


class TestCreateSandbox:
    def test_returns_sandbox(self):
        s = create_sandbox()
        assert s is not None
        assert hasattr(s, "execute")
        assert hasattr(s, "is_available")


class TestDockerSandbox:
    @pytest.fixture
    def sandbox(self):
        from lingji_agent.execution.sandbox import DockerSandbox
        s = DockerSandbox()
        if not s.is_available():
            pytest.skip("Docker 不可用")
        return s

    @pytest.mark.asyncio
    async def test_execute_echo(self, sandbox):
        result = await sandbox.execute(["echo", "hello from docker"])
        assert result.exit_code == 0
        assert "hello from docker" in result.stdout

    @pytest.mark.asyncio
    async def test_execute_python(self, sandbox):
        result = await sandbox.execute(["python", "-c", "print(42)"])
        assert result.exit_code == 0
        assert "42" in result.stdout

    @pytest.mark.asyncio
    async def test_network_isolation(self, sandbox):
        result = await sandbox.execute(
            ["python", "-c", "import urllib.request; urllib.request.urlopen('http://1.1.1.1', timeout=3)"]
        )
        assert result.exit_code != 0

    @pytest.mark.asyncio
    async def test_memory_limit(self, sandbox):
        result = await sandbox.execute(
            ["python", "-c", "bytearray(500 * 1024 * 1024)"],
            limits=ResourceLimits(memory_mb=256, timeout_sec=10)
        )
        assert result.exit_code != 0

    @pytest.mark.asyncio
    async def test_timeout(self, sandbox):
        result = await sandbox.execute(
            ["sleep", "10"],
            limits=ResourceLimits(timeout_sec=2)
        )
        assert result.timed_out is True

    @pytest.mark.asyncio
    async def test_workspace_mounted_readonly(self, sandbox):
        result = await sandbox.execute(
            ["touch", "/workspace/should_fail.txt"]
        )
        assert result.exit_code != 0
