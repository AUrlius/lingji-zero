"""Fleet 4.0a job tools tests"""

from lingji_agent.execution.tools.job_tools import format_job_close_message


def test_format_job_close_message_completed():
    msg = format_job_close_message({
        "job_id": "LJ-A1B2C3D4",
        "status": "completed",
        "summary": "LJ-A1B2C3D4 已完成。空城记 → 青铜剑：a.txt 已保存。",
    })
    assert "LJ-A1B2C3D4" in msg
    assert "已完成" in msg


def test_format_job_close_message_failed():
    msg = format_job_close_message({"job_id": "LJ-DEADBEEF", "status": "failed"})
    assert "LJ-DEADBEEF" in msg
    assert "失败" in msg
