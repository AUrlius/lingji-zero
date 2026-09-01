"""filter_tool_args: 系统注入的多余关键字不能打进工具。"""

from lingji_agent.cognitive.orchestrator import filter_tool_args
from lingji_agent.execution.tools.job_tools import job_invoke


def test_strips_thread_id_from_job_invoke():
    filtered = filter_tool_args(
        job_invoke,
        {
            "user_id": "u1",
            "playbook_id": "agent.status",
            "thread_id": "should-not-pass",
            "intent": "检查上海",
        },
    )
    assert "thread_id" not in filtered
    assert filtered["user_id"] == "u1"
    assert filtered["playbook_id"] == "agent.status"
    assert filtered["intent"] == "检查上海"


def test_keeps_kwargs_for_var_keyword():
    def swallow(**kwargs):
        return kwargs

    args = {"a": 1, "thread_id": "t"}
    assert filter_tool_args(swallow, args) == args
