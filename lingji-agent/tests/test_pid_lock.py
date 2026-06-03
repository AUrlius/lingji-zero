"""PID 文件锁单元测试"""

import os

import pytest

from lingji_agent.foundation import pid_lock


@pytest.fixture
def pid_file(tmp_path, monkeypatch):
    path = tmp_path / "lingji-agent.pid"
    monkeypatch.setattr(pid_lock, "PID_FILE", str(path))
    yield str(path)
    if os.path.exists(path):
        os.remove(path)


class TestPidLock:
    def test_acquire_and_release(self, pid_file):
        assert pid_lock.acquire_pid_lock() is True
        assert pid_lock.read_pid() == os.getpid()
        pid_lock.release_pid_lock()
        assert not os.path.exists(pid_file)

    def test_second_acquire_rejected(self, pid_file):
        assert pid_lock.acquire_pid_lock() is True
        assert pid_lock.acquire_pid_lock() is False
        pid_lock.release_pid_lock()

    def test_stale_pid_file_cleaned(self, pid_file):
        with open(pid_file, "w") as f:
            f.write("999999")
        assert pid_lock.acquire_pid_lock() is True
        pid_lock.release_pid_lock()

    def test_agent_status_running(self, pid_file):
        pid_lock.acquire_pid_lock()
        assert pid_lock.agent_status() == os.getpid()
        pid_lock.release_pid_lock()
        assert pid_lock.agent_status() is None

    def test_stop_no_agent(self, pid_file, capsys):
        assert pid_lock.stop_running_agent() is True
        assert "无运行中的 Agent" in capsys.readouterr().out

    def test_release_only_own_pid(self, pid_file):
        with open(pid_file, "w") as f:
            f.write("424242")
        pid_lock.release_pid_lock()
        assert os.path.exists(pid_file)
        pid_lock.acquire_pid_lock()
        pid_lock.release_pid_lock()
        assert not os.path.exists(pid_file)
