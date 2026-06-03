"""协议模块单元测试"""

import json
import pytest
from lingji_agent.network.protocol import Message, MsgType, parse_message, build_agent_res_payload, parse_attachments


class TestProtocol:
    def test_message_serialization(self):
        msg = Message(
            msg_type=MsgType.CMD_TEXT,
            device_id="test-device",
            payload={"text": "hello"},
        )
        json_str = msg.to_json()
        assert "CMD_TEXT" in json_str
        assert "test-device" in json_str

    def test_message_deserialization(self):
        raw = json.dumps({
            "msg_id": "abc-123",
            "msg_type": "HEARTBEAT",
            "device_id": "test-device",
            "payload": {},
        })
        msg = parse_message(raw)
        assert msg.msg_type == MsgType.HEARTBEAT
        assert msg.device_id == "test-device"

    def test_all_msg_types(self):
        for mt in MsgType:
            msg = Message(msg_type=mt, device_id="t")
            assert msg.msg_type == mt

    def test_agent_res_target_device_id(self):
        payload = build_agent_res_payload("ok", target_device_id="phone-xyz")
        assert payload["target_device_id"] == "phone-xyz"

    def test_agent_res_attachments(self):
        payload = build_agent_res_payload(
            "已找到文件",
            [
                {
                    "file_id": "abc",
                    "name": "test.pdf",
                    "size_bytes": 1024,
                    "mime": "application/pdf",
                    "download_path": "/files/abc?token=secret",
                }
            ],
        )
        msg = Message(msg_type=MsgType.AGENT_RES, device_id="pc", payload=payload)
        parsed = parse_message(msg.to_json())
        attachments = parse_attachments(parsed.payload)
        assert len(attachments) == 1
        assert attachments[0].name == "test.pdf"
        assert attachments[0].download_path.startswith("/files/")
