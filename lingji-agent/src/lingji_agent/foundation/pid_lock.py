"""Agent 单实例 PID 文件锁 — 防止多进程抢占 lingji-pc device_id"""

import os
import signal
import sys
import time

PID_FILE = "/tmp/lingji-agent.pid"
DEFAULT_STOP_TIMEOUT = 10.0


def read_pid() -> int | None:
    if not os.path.exists(PID_FILE):
        return None
    try:
        with open(PID_FILE) as f:
            return int(f.read().strip())
    except (ValueError, OSError):
        return None


def is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def acquire_pid_lock() -> bool:
    """获取锁；False 表示已有实例在运行。"""
    if os.path.exists(PID_FILE):
        old_pid = read_pid()
        if old_pid is not None and is_process_alive(old_pid):
            print(
                f"❌ Agent 已在运行 (PID={old_pid})。\n"
                f"   重启: python -m lingji_agent.main --stop && python -m lingji_agent.main\n"
                f"   或: kill {old_pid}",
                file=sys.stderr,
            )
            return False
        try:
            os.remove(PID_FILE)
        except OSError:
            pass

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    return True


def release_pid_lock(pid: int | None = None) -> None:
    """仅当 PID 文件属于当前进程（或指定 pid）时删除。"""
    if not os.path.exists(PID_FILE):
        return
    owner = read_pid()
    expected = pid if pid is not None else os.getpid()
    if owner == expected:
        try:
            os.remove(PID_FILE)
        except OSError:
            pass


def agent_status() -> int | None:
    """返回运行中 Agent 的 PID，无则 None。"""
    pid = read_pid()
    if pid is None:
        return None
    if is_process_alive(pid):
        return pid
    try:
        os.remove(PID_FILE)
    except OSError:
        pass
    return None


def stop_running_agent(
    sig: int = signal.SIGTERM,
    timeout: float = DEFAULT_STOP_TIMEOUT,
) -> bool:
    """停止已记录的 Agent 进程并清理 PID 文件。"""
    pid = agent_status()
    if pid is None:
        print("无运行中的 Agent")
        return True

    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        release_pid_lock(pid)
        print(f"Agent 已退出 (PID={pid})")
        return True

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_process_alive(pid):
            release_pid_lock(pid)
            print(f"已停止 Agent (PID={pid})")
            return True
        time.sleep(0.1)

    print(
        f"PID {pid} 在 {timeout:.0f}s 内未退出，可执行: kill -9 {pid}",
        file=sys.stderr,
    )
    return False
