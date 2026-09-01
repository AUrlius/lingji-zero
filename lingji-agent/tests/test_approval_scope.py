"""approval_scope 单元测试 — Fleet 4.0d WP1"""

from datetime import datetime, timedelta, timezone

from lingji_agent.execution.approval_scope import (
    default_scope,
    validate_path,
    validate_playbook,
)

NOW = datetime(2026, 8, 31, 9, 0, 0, tzinfo=timezone.utc)


class TestMatch:
    def test_default_scope_matches_playbook(self):
        scope = default_scope("agent.restart", now=NOW)
        assert scope["playbooks"] == ["agent.restart"]
        assert scope["allowed_paths"] == ["/mnt/e/LingjiPlan/LingjiZero"]
        assert scope["auto_approve_tier0"] is True
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
