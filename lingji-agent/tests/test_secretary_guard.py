"""secretary_guard 单元测试 — Fleet 4.0d WP4 helper"""

from lingji_agent.execution.secretary_guard import (
    remote_ops_intent,
    should_block_execute_command,
)


class TestRemoteOpsIntent:
    def test_fleet_send(self):
        assert remote_ops_intent("please fleet send this file to shanghai")
        assert remote_ops_intent("用 fleet_send_file 把文档发出去")

    def test_bronze_sword(self):
        assert remote_ops_intent("把补丁发给青铜剑")

    def test_shanghai_ops(self):
        assert remote_ops_intent("上海运维帮我拉代码")

    def test_restart_agent(self):
        assert remote_ops_intent("请重启 agent")
        assert remote_ops_intent("please restart agent on the pc")

    def test_guardian_status(self):
        assert remote_ops_intent("检查值守状态")
        assert remote_ops_intent("检查上海 Agent 状态")

    def test_benign_chat(self):
        assert not remote_ops_intent("今天天气怎么样")
        assert not remote_ops_intent("summarize this markdown file")


class TestShouldBlockExecuteCommand:
    def test_blocks_scheduler_with_remote_ops(self):
        assert should_block_execute_command(
            is_scheduler=True,
            user_text="请重启 agent 并检查值守状态",
            command="ls -la",
        )

    def test_allows_non_scheduler(self):
        assert not should_block_execute_command(
            is_scheduler=False,
            user_text="请重启 agent",
            command="systemctl restart lingji-agent",
        )

    def test_allows_scheduler_without_remote_intent(self):
        assert not should_block_execute_command(
            is_scheduler=True,
            user_text="帮我写个会议纪要",
            command="ls",
        )
