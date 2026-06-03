"""沙箱混沌抽检 — NativeSandbox 超时 — 四期 4.4"""

import asyncio

import pytest

from lingji_agent.execution.sandbox import NativeSandbox, ResourceLimits


class TestSandboxChaos:
    @pytest.mark.asyncio
    async def test_native_sandbox_timeout_on_long_sleep(self):
        sandbox = NativeSandbox()
        limits = ResourceLimits(timeout_sec=1)
        result = await sandbox.execute(
            ["python3", "-c", "import time; time.sleep(5)"],
            limits=limits,
        )
        assert result.timed_out is True
        assert result.exit_code != 0
        assert "超时" in result.stderr

    @pytest.mark.asyncio
    async def test_native_sandbox_fast_command_ok(self):
        sandbox = NativeSandbox()
        result = await sandbox.execute(
            ["python3", "-c", "print('ok')"],
            limits=ResourceLimits(timeout_sec=5),
        )
        assert result.exit_code == 0
        assert "ok" in result.stdout
