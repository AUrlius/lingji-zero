"""G6 send_file_to_user 与 format_response attachments 测试"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from lingji_agent.cognitive.orchestrator import _collect_attachments, format_response
from lingji_agent.execution.tools import file_tools  # noqa: F401 — register tool
from lingji_agent.execution.registry import registry


@pytest.fixture
def tmp_allowed_file(tmp_path):
    """在 pytest tmp_path（通常位于 /tmp）下创建测试文件。"""
    f = tmp_path / "g6-test.txt"
    f.write_text("g6 payload", encoding="utf-8")
    return f


class TestCollectAttachments:
    def test_merge_from_send_file_tool(self):
        tool_results = [
            {
                "tool_name": "send_file_to_user",
                "result": json.dumps(
                    {
                        "attachments": [
                            {
                                "file_id": "id1",
                                "name": "a.pdf",
                                "size_bytes": 10,
                                "mime": "application/pdf",
                                "download_path": "/files/id1?token=t",
                            }
                        ]
                    }
                ),
            }
        ]
        assert len(_collect_attachments(tool_results)) == 1

    def test_format_response_injects_attachments(self):
        state = {
            "final_response": "",
            "messages": [],
            "tool_results": [
                {
                    "tool_name": "send_file_to_user",
                    "result": json.dumps(
                        {
                            "attachments": [
                                {
                                    "file_id": "x",
                                    "name": "b.txt",
                                    "size_bytes": 3,
                                    "mime": "text/plain",
                                    "download_path": "/files/x?token=y",
                                }
                            ]
                        }
                    ),
                }
            ],
        }
        out = format_response(state)
        assert out["attachments"]
        assert "下载" in out["final_response"]


class TestSendFileToUser:
    @pytest.mark.asyncio
    async def test_upload_by_path(self, tmp_allowed_file):
        tool = registry.get("send_file_to_user")
        assert tool is not None

        mock_upload = AsyncMock(
            return_value={
                "file_id": "fid",
                "name": tmp_allowed_file.name,
                "size_bytes": tmp_allowed_file.stat().st_size,
                "mime": "text/plain",
                "download_path": "/files/fid?token=tok",
            }
        )
        with patch(
            "lingji_agent.execution.tools.file_tools.upload_file_to_gateway",
            mock_upload,
        ):
            result = await tool.fn(paths=[str(tmp_allowed_file)])

        assert result.get("attachments")
        assert result["attachments"][0]["file_id"] == "fid"
        mock_upload.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rejects_blocked_path(self, tmp_path):
        tool = registry.get("send_file_to_user")
        bad = tmp_path / "secret.txt"
        bad.write_text("x")
        result = await tool.fn(paths=[str(bad)])
        assert "error" in result

    @pytest.mark.asyncio
    async def test_sensitive_filename(self, tmp_allowed_file):
        tool = registry.get("send_file_to_user")
        sensitive = tmp_allowed_file.parent / "合同-final.pdf"
        sensitive.write_bytes(b"pdf")
        result = await tool.fn(paths=[str(sensitive)])
        assert result.get("sensitive") is True
