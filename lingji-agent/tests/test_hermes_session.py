"""CMD_HERMES_SESSION 控制面 stub — 不进 LLM。"""

from lingji_agent.execution.hermes_session import handle_hermes_session
from lingji_agent.network.protocol import Message, MsgType, parse_message


class TestHandleHermesSession:
    def test_health_off_when_probe_false(self):
        out = handle_hermes_session("health", probe=lambda: False)
        assert out["action"] == "health"
        assert out["unimplemented"] is False
        assert out["hermes_status"] == "off"
        assert out["channel_ready"] is False

    def test_health_online_when_probe_true(self):
        out = handle_hermes_session("health", probe=lambda: True)
        assert out["hermes_status"] == "online"
        assert out["channel_ready"] is False
        assert out["unimplemented"] is False

    def test_start_never_fakes_online(self):
        out = handle_hermes_session("start", probe=lambda: True)
        assert out["action"] == "start"
        assert out["unimplemented"] is True
        assert out["hermes_status"] == "off"
        assert out["channel_ready"] is False

    def test_stop_unimplemented(self):
        out = handle_hermes_session("stop", probe=lambda: True)
        assert out["unimplemented"] is True
        assert out["hermes_status"] == "off"

    def test_unknown_action_is_health(self):
        out = handle_hermes_session("explode", probe=lambda: False)
        assert out["action"] == "health"

    def test_probe_exception_is_off(self):
        def boom():
            raise RuntimeError("no pgrep")

        out = handle_hermes_session("health", probe=boom)
        assert out["hermes_status"] == "off"


class TestProtocol:
    def test_cmd_hermes_session_roundtrip(self):
        msg = Message(
            msg_type=MsgType.CMD_HERMES_SESSION,
            device_id="user-1",
            payload={"action": "health", "target_agent_id": "lingji-pc"},
        )
        parsed = parse_message(msg.to_json())
        assert parsed.msg_type == MsgType.CMD_HERMES_SESSION
        assert parsed.payload["action"] == "health"
