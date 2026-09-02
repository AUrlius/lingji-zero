import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lingji_agent.execution.coding_supervisor import (
    build_evidence,
    detect_needs_input,
    git_url_allowed,
    job_work_dir,
    kill_process_tree,
    log_tail,
    normalize_git_url,
    pid_alive,
    prepare_job_workspace,
    release_lock,
    run_coding_cli,
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


def _job(tmp_path: Path) -> Path:
    job_dir, reason = prepare_job_workspace(
        jobs_root=tmp_path,
        job_id="LJ-ABCD1234",
        step_id="s1",
        brief="hello",
        runner="cursor",
        timeout_sec=60,
    )
    assert reason == ""
    assert job_dir is not None
    return job_dir


def _py(tmp_path: Path, name: str, body: str) -> list[str]:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return [sys.executable, "-u", str(path)]


def test_log_tail_last_bytes_and_missing(tmp_path: Path):
    path = tmp_path / "run.log"
    path.write_bytes(b"A" * 5000 + b"TAIL")
    text = log_tail(path, max_bytes=4096)
    assert text.endswith("TAIL")
    assert len(text.encode("utf-8")) <= 4096
    assert log_tail(tmp_path / "no-such.log") == ""


def test_build_evidence_matches_spec_fields(tmp_path: Path):
    log_path = tmp_path / "run.log"
    log_path.write_text("hello log", encoding="utf-8")
    summary_path = tmp_path / "summary.md"
    summary_path.write_text("did the thing", encoding="utf-8")
    ev = build_evidence(
        runner="cursor",
        workspace=tmp_path / "workspace",
        exit_code=0,
        reason="ok",
        log_path=log_path,
        summary_path=summary_path,
        questions_path=tmp_path / "questions.md",
    )
    assert ev == {
        "runner": "cursor",
        "workspace": str(tmp_path / "workspace"),
        "exit_code": 0,
        "reason": "ok",
        "log_tail": "hello log",
        "summary": "did the thing",
    }


def test_build_evidence_needs_input_adds_questions(tmp_path: Path):
    questions_path = tmp_path / "questions.md"
    questions_path.write_text("Please choose A", encoding="utf-8")
    ev = build_evidence(
        runner="cursor",
        workspace=tmp_path,
        exit_code=None,
        reason="needs_input",
        log_path=tmp_path / "missing.log",
        summary_path=tmp_path / "missing.md",
        questions_path=questions_path,
    )
    assert ev["questions"] == "Please choose A"
    assert ev["summary"] == ""
    assert ev["log_tail"] == ""
    assert ev["reason"] == "needs_input"


def test_kill_process_tree_kills_session():
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        kill_process_tree(proc.pid)
        proc.wait(timeout=2)
        assert proc.poll() is not None
        assert pid_alive(proc.pid) is False
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)


@pytest.mark.asyncio
async def test_run_coding_cli_ok_writes_pid_summary_stdin_devnull(tmp_path: Path):
    job_dir = _job(tmp_path)
    start_cmd = _py(
        tmp_path,
        "ok_run.py",
        "from pathlib import Path\n"
        "import sys\n"
        "Path('hello.txt').write_text('ok')\n"
        "Path('../out/summary.md').write_text('all good')\n"
        "Path('stdin.txt').write_text('empty' if sys.stdin.read() == '' else 'data')\n",
    )
    result = await run_coding_cli(
        start_cmd=start_cmd,
        job_dir=job_dir,
        timeout_sec=5,
        hung_sec=5,
        heartbeat_sec=0.05,
        progress_sec=10,
    )
    assert result["reason"] == "ok"
    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert (job_dir / "workspace" / "hello.txt").read_text(encoding="utf-8") == "ok"
    assert (job_dir / "workspace" / "stdin.txt").read_text(encoding="utf-8") == "empty"
    assert (job_dir / ".pid").read_text(encoding="utf-8").strip().isdigit()
    assert (job_dir / "logs" / "heartbeat").read_text(encoding="utf-8").strip().endswith("Z")
    assert result["evidence"]["summary"] == "all good"
    assert result["evidence"]["reason"] == "ok"
    assert result["evidence"]["runner"] == "cursor"


@pytest.mark.asyncio
async def test_run_coding_cli_please_choose_needs_input(tmp_path: Path):
    job_dir = _job(tmp_path)
    start_cmd = _py(
        tmp_path,
        "choose.py",
        "print('Please choose', flush=True)\nimport time\ntime.sleep(60)\n",
    )
    result = await run_coding_cli(
        start_cmd=start_cmd,
        job_dir=job_dir,
        timeout_sec=5,
        hung_sec=5,
        heartbeat_sec=0.05,
        progress_sec=10,
    )
    assert result["reason"] == "needs_input"
    assert result["ok"] is False
    questions = (job_dir / "out" / "questions.md").read_text(encoding="utf-8")
    assert "Please choose" in questions
    assert result["evidence"]["questions"]
    assert "Please choose" in result["evidence"]["log_tail"]


@pytest.mark.asyncio
async def test_run_coding_cli_timeout(tmp_path: Path):
    job_dir = _job(tmp_path)
    result = await run_coding_cli(
        start_cmd=_py(tmp_path, "sleep30.py", "import time\ntime.sleep(30)\n"),
        job_dir=job_dir,
        timeout_sec=0.5,
        hung_sec=30,
        heartbeat_sec=0.1,
        progress_sec=10,
    )
    assert result["reason"] == "timeout"
    assert result["ok"] is False
    assert pid_alive(int((job_dir / ".pid").read_text(encoding="utf-8").strip())) is False


@pytest.mark.asyncio
async def test_run_coding_cli_hung_no_log_growth(tmp_path: Path):
    job_dir = _job(tmp_path)
    result = await run_coding_cli(
        start_cmd=_py(tmp_path, "sleep30.py", "import time\ntime.sleep(30)\n"),
        job_dir=job_dir,
        timeout_sec=30,
        hung_sec=0.4,
        heartbeat_sec=0.1,
        progress_sec=10,
    )
    assert result["reason"] == "hung"
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_run_coding_cli_crash_nonzero(tmp_path: Path):
    job_dir = _job(tmp_path)
    result = await run_coding_cli(
        start_cmd=[sys.executable, "-u", "-c", "raise SystemExit(7)"],
        job_dir=job_dir,
        timeout_sec=5,
        hung_sec=5,
        heartbeat_sec=0.05,
        progress_sec=10,
    )
    assert result["reason"] == "crash"
    assert result["ok"] is False
    assert result["exit_code"] == 7


@pytest.mark.asyncio
async def test_run_coding_cli_runner_missing_empty_cmd(tmp_path: Path):
    job_dir = _job(tmp_path)
    result = await run_coding_cli(
        start_cmd=[],
        job_dir=job_dir,
        timeout_sec=5,
        hung_sec=5,
        heartbeat_sec=0.1,
        progress_sec=10,
    )
    assert result["reason"] == "runner_missing"
    assert result["ok"] is False
    assert not (job_dir / ".pid").exists()


@pytest.mark.asyncio
async def test_run_coding_cli_runner_missing_shell_meta(tmp_path: Path):
    job_dir = _job(tmp_path)
    result = await run_coding_cli(
        start_cmd=["python3;true"],
        job_dir=job_dir,
        timeout_sec=5,
        hung_sec=5,
        heartbeat_sec=0.1,
        progress_sec=10,
    )
    assert result["reason"] == "runner_missing"
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_run_coding_cli_runner_missing_binary(tmp_path: Path):
    job_dir = _job(tmp_path)
    result = await run_coding_cli(
        start_cmd=["/no/such/lingji-coding-runner"],
        job_dir=job_dir,
        timeout_sec=5,
        hung_sec=5,
        heartbeat_sec=0.1,
        progress_sec=10,
    )
    assert result["reason"] == "runner_missing"
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_run_coding_cli_on_progress_counted_not_concluding(tmp_path: Path):
    job_dir = _job(tmp_path)
    calls: list[dict] = []
    result = await run_coding_cli(
        start_cmd=_py(tmp_path, "sleep045.py", "import time\ntime.sleep(0.45)\n"),
        job_dir=job_dir,
        timeout_sec=5,
        hung_sec=5,
        heartbeat_sec=0.1,
        progress_sec=0.15,
        on_progress=calls.append,
    )
    assert result["reason"] == "ok"
    assert len(calls) >= 1
    assert all("log_tail" in item for item in calls)
