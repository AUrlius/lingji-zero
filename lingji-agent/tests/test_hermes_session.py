"""CMD_HERMES_SESSION — 真启停 + 本机 chat 适配（不进 LLM）。"""

from lingji_agent.execution.hermes_session import (
    NO_CHAT_API,
    NO_START_CMD,
    HermesSessionClient,
    argv_list,
    fleet_kick_reason,
    handle_hermes_session,
    is_loopback_url,
)
from lingji_agent.foundation.config import HermesSessionConfig
from lingji_agent.network.protocol import Message, MsgType, parse_message
import pytest


class TestArgvAndUrls:
    def test_argv_rejects_shell_meta(self):
        with pytest.raises(ValueError):
            argv_list(["hermes;rm", "-rf"])

    def test_loopback_only(self):
        assert is_loopback_url("http://127.0.0.1:18789/health")
        assert is_loopback_url("http://localhost/v1/chat")
        assert not is_loopback_url("http://example.com/health")
        assert not is_loopback_url("http://192.168.1.8:18789/chat")
        assert not is_loopback_url("")


class TestHandleHermesSession:
    def test_health_off_when_probe_false(self):
        out = handle_hermes_session("health", probe=lambda: False)
        assert out["action"] == "health"
        assert out["unimplemented"] is False
        assert out["hermes_status"] == "off"
        assert out["channel_ready"] is False

    def test_health_online_when_probe_true_without_chat_url(self):
        out = handle_hermes_session("health", probe=lambda: True)
        assert out["hermes_status"] == "online"
        assert out["channel_ready"] is False
        assert out["unimplemented"] is False
        assert "未接通" in out["reason"]

    def test_health_channel_ready_with_loopback_chat_url(self):
        cfg = HermesSessionConfig(chat_url="http://127.0.0.1:18789/v1/chat")
        out = handle_hermes_session("health", cfg=cfg, probe=lambda: True)
        assert out["channel_ready"] is True

    def test_start_attaches_when_already_running(self):
        spawned = []
        cfg = HermesSessionConfig(start_cmd=["hermes", "gateway"])
        out = handle_hermes_session(
            "start",
            cfg=cfg,
            probe=lambda: True,
            runner=lambda argv, detach=False: spawned.append(argv) or (0, ""),
            settle_sec=0,
        )
        assert out["unimplemented"] is False
        assert out["hermes_status"] == "online"
        assert out["ok"] is True
        assert "附着" in out["reason"]
        assert spawned == []

    def test_start_without_cmd_stays_off(self):
        out = handle_hermes_session(
            "start",
            cfg=HermesSessionConfig(),
            probe=lambda: False,
            settle_sec=0,
        )
        assert out["unimplemented"] is False
        assert out["hermes_status"] == "off"
        assert out["ok"] is False
        assert NO_START_CMD[:8] in out["reason"]

    def test_start_spawns_once_and_probes(self, monkeypatch):
        monkeypatch.setattr(
            "lingji_agent.execution.hermes_session.shutil.which",
            lambda exe: "/usr/bin/" + exe,
        )
        running = {"v": False}
        calls = []

        def runner(argv, detach=False):
            calls.append((list(argv), detach))
            running["v"] = True
            return 0, ""

        cfg = HermesSessionConfig(start_cmd=["hermes", "gateway"])
        out = handle_hermes_session(
            "start",
            cfg=cfg,
            probe=lambda: running["v"],
            runner=runner,
            settle_sec=0,
        )
        assert out["hermes_status"] == "online"
        assert out["unimplemented"] is False
        assert calls == [(["hermes", "gateway"], True)]

    def test_stop_runs_cmd_and_goes_off(self):
        running = {"v": True}
        calls = []

        def runner(argv, detach=False):
            calls.append(list(argv))
            running["v"] = False
            return 0, ""

        cfg = HermesSessionConfig(stop_cmd=["pkill", "-x", "hermes"])
        out = handle_hermes_session(
            "stop",
            cfg=cfg,
            probe=lambda: running["v"],
            runner=runner,
            settle_sec=0,
        )
        assert out["unimplemented"] is False
        assert out["hermes_status"] == "off"
        assert calls == [["pkill", "-x", "hermes"]]

    def test_unknown_action_is_health(self):
        out = handle_hermes_session("explode", probe=lambda: False)
        assert out["action"] == "health"

    def test_probe_exception_is_off(self):
        def boom():
            raise RuntimeError("no pgrep")

        out = handle_hermes_session("health", probe=boom)
        assert out["hermes_status"] == "off"


class TestHermesChat:
    def test_kick_fleet_intent(self):
        assert fleet_kick_reason("请发给青铜剑一份报告")
        cfg = HermesSessionConfig(chat_url="http://127.0.0.1:9/chat")
        out = handle_hermes_session(
            "chat",
            cfg=cfg,
            probe=lambda: True,
            text="发给青铜剑看一下",
        )
        assert out["ok"] is False
        assert out["channel_ready"] is True
        assert "中间栏" in out["text"]
        assert "秘书" in out["text"]

    def test_chat_without_api_is_honest(self):
        out = handle_hermes_session(
            "chat",
            cfg=HermesSessionConfig(),
            probe=lambda: True,
            text="你好",
        )
        assert out["channel_ready"] is False
        assert out["hermes_status"] == "online"
        assert out["text"] == NO_CHAT_API

    def test_chat_posts_to_localhost(self):
        cfg = HermesSessionConfig(chat_url="http://127.0.0.1:18789/v1/chat")
        client = HermesSessionClient("http://127.0.0.1:18789/v1/chat")
        client.send_chat = lambda text: f"回:{text}"  # type: ignore[method-assign]
        out = handle_hermes_session(
            "chat",
            cfg=cfg,
            probe=lambda: True,
            client=client,
            text="本机一句",
        )
        assert out["ok"] is True
        assert out["channel_ready"] is True
        assert out["text"] == "回:本机一句"


class TestProtocol:
    def test_cmd_hermes_session_roundtrip(self):
        msg = Message(
            msg_type=MsgType.CMD_HERMES_SESSION,
            device_id="user-1",
            payload={"action": "chat", "text": "hi", "target_agent_id": "lingji-laptop"},
        )
        parsed = parse_message(msg.to_json())
        assert parsed.msg_type == MsgType.CMD_HERMES_SESSION
        assert parsed.payload["action"] == "chat"
        assert parsed.payload["text"] == "hi"
