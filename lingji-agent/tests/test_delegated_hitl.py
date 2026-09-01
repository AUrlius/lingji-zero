"""delegated HITL helpers — Fleet 4.0d-3"""

import pytest

from lingji_agent.execution.approval_scope import default_scope
from lingji_agent.execution.delegated_hitl import (
    attach_job_fields,
    decide_delegate,
    handle_scheduler_hitl_req,
    user_escalate_payload,
)
from lingji_agent.network.protocol import MsgType

NOW_SCOPE = default_scope("agent.status")


def test_attach_no_job_is_user():
    fields = attach_job_fields(None, "execute_command", {"command": "ls"}, executor_id="lingji-pc")
    assert fields["escalation"] == "user"
    assert fields["job_id"] == ""


def test_attach_in_scope_execute_command():
    job = {
        "job_id": "LJ-1",
        "scheduler_agent_id": "lingji-laptop",
        "approval_scope": NOW_SCOPE,
        "steps": [{"step_id": "LJ-1-S1", "status": "running"}],
    }
    fields = attach_job_fields(job, "execute_command", {"command": "uname"}, executor_id="lingji-pc")
    assert fields["escalation"] == "scheduler"
    assert fields["job_id"] == "LJ-1"
    assert fields["step_id"] == "LJ-1-S1"
    assert fields["scheduler_agent_id"] == "lingji-laptop"


def test_decide_delegate_sensitive_escalates():
    job = {
        "job_id": "LJ-1",
        "approval_scope": NOW_SCOPE,
        "scheduler_agent_id": "lingji-laptop",
    }
    payload = {"tool": "delete_file", "tool_args": {"path": "~/.ssh/id_rsa"}}
    assert decide_delegate(payload, job) == "escalate_user"
    payload2 = {
        "tool": "delete_file",
        "tool_args": {"path": "/mnt/e/LingjiPlan/LingjiZero/x.txt"},
    }
    assert decide_delegate(payload2, job) == "approve"


def test_user_escalate_payload_overrides():
    orig = {"task_id": "t1", "escalation": "scheduler", "tool": "execute_command"}
    out = user_escalate_payload(orig)
    assert out["escalation"] == "user"
    assert out["task_id"] == "t1"
    assert orig["escalation"] == "scheduler"


def _job_in_scope(job_id="LJ-1"):
    return {
        "job_id": job_id,
        "status": "running",
        "scheduler_agent_id": "lingji-laptop",
        "approval_scope": NOW_SCOPE,
        "plan": {"executor_id": "lingji-pc"},
    }


@pytest.mark.asyncio
async def test_handler_approve_in_scope_sends_hitl_res():
    sent = []

    async def send(msg):
        sent.append(msg)

    async def get_job(job_id):
        return _job_in_scope(job_id)

    payload = {
        "task_id": "t-ok",
        "agent_id": "lingji-pc",
        "job_id": "LJ-1",
        "escalation": "scheduler",
        "tool": "execute_command",
        "tool_args": {"command": "uname -a"},
        "target_user_id": "user-1",
    }
    action = await handle_scheduler_hitl_req(
        payload,
        send=send,
        get_job=get_job,
        device_id="lingji-laptop",
    )
    assert action == "approved"
    assert len(sent) == 1
    assert sent[0].msg_type == MsgType.HITL_RES
    assert sent[0].payload["decision"] == "approved"
    assert sent[0].payload["target_agent_id"] == "lingji-pc"
    assert sent[0].payload["responded_by"] == "scheduler"


@pytest.mark.asyncio
async def test_handler_sensitive_escalates_user():
    sent = []

    async def send(msg):
        sent.append(msg)

    async def get_job(job_id):
        return _job_in_scope(job_id)

    payload = {
        "task_id": "t-ssh",
        "agent_id": "lingji-pc",
        "job_id": "LJ-1",
        "escalation": "scheduler",
        "tool": "delete_file",
        "tool_args": {"path": "~/.ssh/id_rsa"},
        "target_user_id": "user-1",
    }
    action = await handle_scheduler_hitl_req(
        payload,
        send=send,
        get_job=get_job,
        device_id="lingji-laptop",
    )
    assert action == "escalate_user"
    assert len(sent) == 1
    assert sent[0].msg_type == MsgType.HITL_REQ
    assert sent[0].payload["escalation"] == "user"
    assert sent[0].payload["task_id"] == "t-ssh"
    assert sent[0].payload["target_user_id"] == "user-1"


@pytest.mark.asyncio
async def test_handler_ignores_user_escalation():
    sent = []

    async def send(msg):
        sent.append(msg)

    async def get_job(_job_id):
        raise AssertionError("should not fetch job")

    action = await handle_scheduler_hitl_req(
        {
            "task_id": "t-user",
            "agent_id": "lingji-pc",
            "escalation": "user",
            "tool": "execute_command",
        },
        send=send,
        get_job=get_job,
        device_id="lingji-laptop",
    )
    assert action == "ignore"
    assert sent == []
