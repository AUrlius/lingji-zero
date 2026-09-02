import json
import os
from pathlib import Path

from lingji_agent.execution.coding_supervisor import (
    detect_needs_input,
    git_url_allowed,
    job_work_dir,
    normalize_git_url,
    pid_alive,
    prepare_job_workspace,
    release_lock,
    try_acquire_lock,
)


def test_normalize_git_url():
    assert normalize_git_url("https://github.com/AUrlius/lingji-zero.git/") == (
        "https://github.com/aurlius/lingji-zero"
    )
    assert normalize_git_url("") == ""


def test_git_url_allowed():
    allow = ["https://github.com/AUrlius/lingji-zero"]
    assert git_url_allowed("https://github.com/AUrlius/lingji-zero.git", allow)
    assert not git_url_allowed("https://evil.example/r", allow)
    assert not git_url_allowed("https://github.com/AUrlius/lingji-zero", [])


def test_detect_needs_input():
    assert detect_needs_input("Please choose A or B")
    assert not detect_needs_input("compiled successfully")


def test_job_work_dir(tmp_path: Path):
    assert job_work_dir(tmp_path, "LJ-ABCD1234") == tmp_path / "LJ-ABCD1234"


def test_pid_alive_self():
    assert pid_alive(os.getpid()) is True
    assert pid_alive(2_147_483_647) is False


def test_prepare_persists_brief_and_meta(tmp_path: Path):
    job_dir, reason = prepare_job_workspace(
        jobs_root=tmp_path,
        job_id="LJ-ABCD1234",
        step_id="s1",
        brief="fix the bug",
        runner="cursor",
        timeout_sec=600,
    )
    assert reason == ""
    assert job_dir == tmp_path / "LJ-ABCD1234"
    assert (job_dir / "brief.md").read_text(encoding="utf-8") == "fix the bug"
    meta = json.loads((job_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["job_id"] == "LJ-ABCD1234"
    assert meta["step_id"] == "s1"
    assert meta["runner"] == "cursor"
    assert meta["timeout_sec"] == 600
    assert meta["started_at"].endswith("Z")
    assert (job_dir / "workspace").is_dir()
    assert (job_dir / "logs").is_dir()
    assert (job_dir / "out").is_dir()


def test_brief_missing_does_not_create_dir(tmp_path: Path):
    job_dir, reason = prepare_job_workspace(
        jobs_root=tmp_path,
        job_id="LJ-ABCD1234",
        step_id="s1",
        brief="",
        runner="cursor",
        timeout_sec=60,
    )
    assert job_dir is None
    assert reason == "brief_missing"
    assert not (tmp_path / "LJ-ABCD1234").exists()


def test_second_lock_fails(tmp_path: Path):
    assert try_acquire_lock(tmp_path, os.getpid()) is True
    assert try_acquire_lock(tmp_path, os.getpid() + 1) is False
    release_lock(tmp_path, os.getpid())
    assert try_acquire_lock(tmp_path, os.getpid() + 1) is True


def test_dead_pid_lock_can_be_stolen(tmp_path: Path):
    lock = tmp_path / ".coding_lock"
    lock.write_text("2147483647", encoding="utf-8")
    assert try_acquire_lock(tmp_path, os.getpid()) is True
    assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())


def test_job_dir_live_pid_executor_busy(tmp_path: Path):
    job = tmp_path / "LJ-ABCD1234"
    job.mkdir()
    (job / ".pid").write_text(str(os.getpid()), encoding="utf-8")
    job_dir, reason = prepare_job_workspace(
        jobs_root=tmp_path,
        job_id="LJ-ABCD1234",
        step_id="s1",
        brief="hello",
        runner="cursor",
        timeout_sec=60,
    )
    assert job_dir is None
    assert reason == "executor_busy"
    assert job.is_dir()
    assert not list(tmp_path.glob("LJ-ABCD1234.stale-*"))


def test_stale_job_dir_renamed_then_rebuilt(tmp_path: Path):
    job = tmp_path / "LJ-ABCD1234"
    job.mkdir()
    (job / ".pid").write_text("2147483647", encoding="utf-8")
    (job / "old.txt").write_text("x", encoding="utf-8")
    job_dir, reason = prepare_job_workspace(
        jobs_root=tmp_path,
        job_id="LJ-ABCD1234",
        step_id="s1",
        brief="hello",
        runner="cursor",
        timeout_sec=60,
    )
    assert reason == ""
    assert job_dir == job
    assert (job / "brief.md").read_text(encoding="utf-8") == "hello"
    assert not (job / "old.txt").exists()
    stale = list(tmp_path.glob("LJ-ABCD1234.stale-*"))
    assert len(stale) == 1
    assert (stale[0] / "old.txt").exists()


def test_disallowed_source_git_does_not_clone(tmp_path: Path):
    calls: list[tuple[str, Path]] = []

    def fake_clone(url: str, dest: Path) -> str | None:
        calls.append((url, dest))
        return None

    job_dir, reason = prepare_job_workspace(
        jobs_root=tmp_path,
        job_id="LJ-ABCD1234",
        step_id="s1",
        brief="hello",
        runner="cursor",
        timeout_sec=60,
        source_git="https://evil.example/r",
        allowlist=["https://github.com/AUrlius/lingji-zero"],
        clone=fake_clone,
    )
    assert job_dir is None
    assert reason == "source_git not allowed"
    assert len(calls) == 0


def test_allowed_source_git_calls_clone(tmp_path: Path):
    calls: list[tuple[str, Path]] = []

    def fake_clone(url: str, dest: Path) -> str | None:
        calls.append((url, dest))
        dest.mkdir(parents=True, exist_ok=True)
        return None

    url = "https://github.com/AUrlius/lingji-zero.git"
    job_dir, reason = prepare_job_workspace(
        jobs_root=tmp_path,
        job_id="LJ-ABCD1234",
        step_id="s1",
        brief="hello",
        runner="cursor",
        timeout_sec=60,
        source_git=url,
        allowlist=["https://github.com/AUrlius/lingji-zero"],
        clone=fake_clone,
    )
    assert reason == ""
    assert job_dir is not None
    assert len(calls) == 1
    assert calls[0][0] == url
    assert calls[0][1] == job_dir / "workspace"
