"""approval_scope 单元测试 — Fleet 4.0d WP1"""

from datetime import datetime, timedelta, timezone

from lingji_agent.execution.approval_scope import (
    ESCALATION_SCHEDULER,
    ESCALATION_USER,
    classify_hitl,
    default_coding_scope,
    default_scope,
    pick_active_job_for_executor,
    validate_coding_scope,
    validate_path,
    validate_playbook,
)
from lingji_agent.execution.coding_supervisor import JOBS_ROOT_SENTINEL

NOW = datetime(2026, 8, 31, 9, 0, 0, tzinfo=timezone.utc)


class TestMatch:
    def test_default_scope_matches_playbook(self):
        scope = default_scope("agent.restart", now=NOW)
        assert scope["playbooks"] == ["agent.restart"]
        assert scope["allowed_paths"] == ["/mnt/e/LingjiPlan/LingjiZero"]
        assert scope["auto_approve_tier0"] is True
        assert scope["auto_approve_hitl_in_scope"] is True
        expires = datetime.fromisoformat(
            scope["expires_at"].replace("Z", "+00:00")
        )
        assert expires == NOW + timedelta(hours=1)
        ok, reason = validate_playbook(scope, "agent.restart", now=NOW)
        assert ok
        assert reason == ""


class TestExpired:
    def test_expired_z_suffix(self):
        scope = {
            "expires_at": "2026-08-31T08:00:00Z",
            "playbooks": ["agent.restart"],
        }
        ok, reason = validate_playbook(scope, "agent.restart", now=NOW)
        assert not ok
        assert reason == "approval_scope expired"

    def test_expired_offset_suffix(self):
        scope = {
            "expires_at": "2026-08-31T08:00:00+00:00",
            "playbooks": ["agent.restart"],
        }
        ok, reason = validate_playbook(scope, "agent.restart", now=NOW)
        assert not ok
        assert reason == "approval_scope expired"


class TestWrongPlaybook:
    def test_playbook_not_in_scope(self):
        scope = default_scope("agent.restart", now=NOW)
        ok, reason = validate_playbook(scope, "git-pull-deploy", now=NOW)
        assert not ok
        assert reason == "playbook not in approval_scope"

    def test_missing_scope(self):
        ok, reason = validate_playbook(None, "agent.restart", now=NOW)
        assert not ok
        assert reason == "approval_scope missing"
        ok, reason = validate_playbook({}, "agent.restart", now=NOW)
        assert not ok
        assert reason == "approval_scope missing"


class TestSensitivePath:
    def test_rejects_ssh_paths(self):
        scope = default_scope("agent.restart", now=NOW)
        for path in (
            "~/.ssh",
            "~/.ssh/id_rsa",
            "/root/.ssh",
            "/home/unix/.ssh/id_rsa",
        ):
            ok, reason = validate_path(scope, path)
            assert not ok, path
            assert reason == "sensitive path"


class TestAllowedPrefix:
    def test_empty_path_ok(self):
        ok, reason = validate_path(None, "")
        assert ok
        assert reason == ""

    def test_lingjizero_prefix_allowed(self):
        scope = default_scope("agent.restart", now=NOW)
        ok, reason = validate_path(
            scope, "/mnt/e/LingjiPlan/LingjiZero/lingji-agent/src"
        )
        assert ok, reason
        assert reason == ""

    def test_outside_prefix_rejected(self):
        scope = default_scope("agent.restart", now=NOW)
        ok, _reason = validate_path(scope, "/tmp/evil")
        assert not ok


class TestClassifyHitl:
    def test_missing_or_expired_is_user(self):
        assert classify_hitl(None, "execute_command", {"command": "ls"}, now=NOW) == ESCALATION_USER
        scope = default_scope("agent.status", now=NOW)
        scope["expires_at"] = "2026-08-31T08:00:00Z"
        assert classify_hitl(scope, "execute_command", {"command": "ls"}, now=NOW) == ESCALATION_USER

    def test_opt_out_is_user(self):
        scope = default_scope("agent.status", now=NOW)
        scope["auto_approve_hitl_in_scope"] = False
        assert classify_hitl(scope, "execute_command", {"command": "ls"}, now=NOW) == ESCALATION_USER

    def test_execute_command_mission_authorized(self):
        scope = default_scope("agent.status", now=NOW)
        assert classify_hitl(scope, "execute_command", {"command": "uname -a"}, now=NOW) == ESCALATION_SCHEDULER

    def test_execute_command_prefix_mismatch(self):
        scope = default_scope("agent.status", now=NOW)
        scope["allowed_commands"] = ["git pull"]
        assert classify_hitl(scope, "execute_command", {"command": "rm -rf /"}, now=NOW) == ESCALATION_USER
        assert (
            classify_hitl(scope, "execute_command", {"command": "git pull --ff-only"}, now=NOW)
            == ESCALATION_SCHEDULER
        )

    def test_delete_file_path_rules(self):
        scope = default_scope("agent.status", now=NOW)
        assert (
            classify_hitl(
                scope,
                "delete_file",
                {"path": "/mnt/e/LingjiPlan/LingjiZero/tmp.txt"},
                now=NOW,
            )
            == ESCALATION_SCHEDULER
        )
        assert classify_hitl(scope, "delete_file", {"path": "~/.ssh/id_rsa"}, now=NOW) == ESCALATION_USER
        assert classify_hitl(scope, "delete_file", {"path": "/tmp/x"}, now=NOW) == ESCALATION_USER

    def test_unknown_tool_is_user(self):
        scope = default_scope("agent.status", now=NOW)
        assert classify_hitl(scope, "move_file", {}, now=NOW) == ESCALATION_USER


class TestCodingScope:
    def test_default_coding_scope(self):
        scope = default_coding_scope(timeout_sec=1800, now=NOW)
        assert scope["playbooks"] == ["coding.cursor"]
        assert scope["runners"] == ["cursor"]
        assert scope["allowed_paths"] == [JOBS_ROOT_SENTINEL]
        assert scope["auto_approve_tier0"] is False
        ok, reason = validate_coding_scope(
            scope,
            playbook_id="coding.cursor",
            runner="cursor",
            jobs_root="/mnt/d/LingjiJobs",
            now=NOW,
        )
        assert ok and reason == ""

    def test_default_coding_scope_timeout_is_4h(self):
        scope = default_coding_scope(now=NOW)
        assert scope["max_timeout_sec"] == 14400

    def test_coding_scope_rejects_runner_and_git(self):
        scope = default_coding_scope(
            source_git="https://github.com/AUrlius/lingji-zero", now=NOW
        )
        ok, reason = validate_coding_scope(
            scope,
            playbook_id="coding.cursor",
            runner="claude",
            jobs_root="/mnt/d/LingjiJobs",
            now=NOW,
        )
        assert not ok and reason == "runner not in approval_scope"
        ok, reason = validate_coding_scope(
            scope,
            playbook_id="coding.cursor",
            runner="cursor",
            jobs_root="/mnt/d/LingjiJobs",
            source_git="https://evil.example/r",
            now=NOW,
        )
        assert not ok and reason == "source_git not in approval_scope"


class TestPickActiveJob:
    def test_picks_newest_bound_executor(self):
        jobs = [
            {
                "job_id": "LJ-OLD",
                "status": "running",
                "updated_at": "2026-08-31T08:00:00Z",
                "plan": {"executor_id": "lingji-pc"},
            },
            {
                "job_id": "LJ-NEW",
                "status": "dispatched",
                "updated_at": "2026-08-31T09:00:00Z",
                "plan": {"executor_id": "lingji-pc"},
            },
            {
                "job_id": "LJ-DONE",
                "status": "completed",
                "updated_at": "2026-08-31T10:00:00Z",
                "plan": {"executor_id": "lingji-pc"},
            },
            {
                "job_id": "LJ-OTHER",
                "status": "running",
                "updated_at": "2026-08-31T11:00:00Z",
                "plan": {"executor_id": "lingji-laptop"},
            },
        ]
        picked = pick_active_job_for_executor(jobs, "lingji-pc")
        assert picked is not None
        assert picked["job_id"] == "LJ-NEW"

    def test_step_executor_id(self):
        jobs = [
            {
                "job_id": "LJ-STEP",
                "status": "waiting",
                "updated_at": "2026-08-31T09:00:00Z",
                "steps": [{"executor_id": "lingji-pc", "status": "running"}],
            }
        ]
        picked = pick_active_job_for_executor(jobs, "lingji-pc")
        assert picked is not None
        assert picked["job_id"] == "LJ-STEP"
