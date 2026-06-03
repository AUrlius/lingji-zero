"""内置工具：系统状态查询 + 命令执行"""

import re

import psutil

from lingji_agent.execution.registry import RiskLevel, registry

_GATEWAY_REDOWNLOAD = re.compile(
    r"\b(curl|wget)\b.*(?:/files/|lingji\.mygoal\.tech)",
    re.IGNORECASE | re.DOTALL,
)


def _blocks_gateway_redownload(command: str) -> bool:
    return bool(_GATEWAY_REDOWNLOAD.search(command))


@registry.register(
    name="system_status",
    description="查询系统状态：CPU、内存、磁盘使用率、运行时间",
    parameters={"type": "object", "properties": {}, "required": []},
    risk=RiskLevel.SAFE,
)
async def system_status() -> dict:
    """获取系统状态摘要"""
    try:
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.5),
            "cpu_count": psutil.cpu_count(),
            "memory_percent": psutil.virtual_memory().percent,
            "memory_total_gb": round(psutil.virtual_memory().total / (1024**3), 1),
            "memory_available_gb": round(psutil.virtual_memory().available / (1024**3), 1),
            "disk_percent": psutil.disk_usage("/").percent,
            "disk_total_gb": round(psutil.disk_usage("/").total / (1024**3), 1),
            "uptime_hours": round(
                (psutil.boot_time() and (__import__("time").time() - psutil.boot_time()) / 3600) or 0, 1
            ),
        }
    except Exception as e:
        return {"error": str(e)}


@registry.register(
    name="execute_command",
    description="在沙箱中执行系统命令。⚠️ 危险操作，会触发 HITL 审批",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的命令，如 'ls -la /tmp'"},
            "cwd": {"type": "string", "description": "工作目录，可选"},
        },
        "required": ["command"],
    },
    risk=RiskLevel.CRITICAL,
)
async def execute_command_tool(command: str, cwd: str | None = None) -> dict:
    """在沙箱中执行命令（CRITICAL 级别，必须触发 HITL）"""
    if _blocks_gateway_redownload(command):
        return {
            "error": "禁止用 curl/wget 从 Gateway 重下上传文件；文件已落盘，请用 move_file 整理",
        }
    from lingji_agent.execution.sandbox import create_sandbox, ResourceLimits

    sandbox = create_sandbox()
    limits = ResourceLimits(timeout_sec=30, memory_mb=256)

    result = await sandbox.execute(
        command=command,
        cwd=cwd,
        limits=limits,
    )

    return {
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_ms": round(result.duration_ms, 1),
        "timed_out": result.timed_out,
    }


@registry.register(
    name="get_processes",
    description="列出当前运行的进程（按 CPU 使用率排序前 10）",
    parameters={"type": "object", "properties": {}, "required": []},
    risk=RiskLevel.SAFE,
)
async def get_processes() -> dict:
    """列出进程"""
    try:
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                procs.append(p.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        procs.sort(key=lambda x: x.get("cpu_percent", 0) or 0, reverse=True)
        return {"processes": procs[:10], "total_count": len(procs)}
    except Exception as e:
        return {"error": str(e)}
