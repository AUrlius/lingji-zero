"""Fleet Phase 3 — fleet_send_file 与 fleet_client 测试"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from lingji_agent.cognitive.orchestrator import _collect_attachments
from lingji_agent.execution.tools import fleet_tools  # noqa: F401 — register tool
from lingji_agent.execution.registry import registry


class TestFleetCollectAttachments:
    def test_merge_from_fleet_to_user(self):
        tool_results = [
            {
                "tool_name": "fleet_send_file",
                "result": json.dumps(
                    {
                        "attachments": [
                            {
                                "file_id": "f1",
                                "name": "cross.pdf",
                                "size_bytes": 10,
                                "mime": "application/pdf",
                                "download_path": "/files/f1?token=t",
                            }
                        ]
                    }
                ),
            }
        ]
        assert len(_collect_attachments(tool_results)) == 1


class TestFleetSendFile:
    @pytest.mark.asyncio
    async def test_transfer_to_agent(self, tmp_path):
        tool = registry.get("fleet_send_file")
        assert tool is not None
        f = tmp_path / "fleet-doc.txt"
        f.write_text("fleet payload", encoding="utf-8")

        mock_upload = AsyncMock(
            return_value={
                "file_id": "fid",
                "name": f.name,
                "size_bytes": f.stat().st_size,
                "mime": "text/plain",
                "download_path": "/files/fid?token=tok",
            }
        )
        mock_transfer = AsyncMock(
            return_value={"transfer_id": "xfer-1", "status": "pending", "to_agent_id": "lingji-pc"},
        )
        mock_register = AsyncMock(return_value={"lingji_file_id": "LF-TEST01"})
        mock_job = AsyncMock(return_value={"job_id": "LJ-TEST01", "status": "planned"})
        with (
            patch(
                "lingji_agent.execution.tools.fleet_tools.upload_file_to_gateway",
                mock_upload,
            ),
            patch(
                "lingji_agent.execution.tools.fleet_tools.request_fleet_transfer",
                mock_transfer,
            ),
            patch(
                "lingji_agent.execution.tools.fleet_tools.register_lingji_file",
                mock_register,
            ),
            patch(
                "lingji_agent.execution.tools.fleet_tools.create_fleet_file_job",
                mock_job,
            ),
            patch(
                "lingji_agent.execution.tools.fleet_tools.fetch_online_agents",
                AsyncMock(return_value=[]),
            ),
        ):
            result = await tool.fn(
                paths=[str(f)],
                to_agent_id="lingji-pc",
                user_id="user-abc",
                thread_id="thread-1",
            )

        assert result.get("status") == "pending"
        assert result.get("transfer_id") == "xfer-1"
        assert result.get("job_id") == "LJ-TEST01"
        mock_transfer.assert_awaited_once()
        call_kwargs = mock_transfer.await_args.kwargs
        assert call_kwargs["to_agent_id"] == "lingji-pc"
        assert call_kwargs["user_id"] == "user-abc"
        assert call_kwargs["job_id"] == "LJ-TEST01"

    @pytest.mark.asyncio
    async def test_transfer_to_user_returns_attachments(self, tmp_path):
        tool = registry.get("fleet_send_file")
        f = tmp_path / "phone-doc.txt"
        f.write_text("phone", encoding="utf-8")

        mock_upload = AsyncMock(
            return_value={
                "file_id": "fid2",
                "name": f.name,
                "size_bytes": 5,
                "mime": "text/plain",
                "download_path": "/files/fid2?token=tok",
            }
        )
        mock_transfer = AsyncMock(return_value={"transfer_id": "xfer-2", "status": "delivered"})
        mock_register = AsyncMock(return_value={"lingji_file_id": "LF-TEST02"})
        with (
            patch(
                "lingji_agent.execution.tools.fleet_tools.upload_file_to_gateway",
                mock_upload,
            ),
            patch(
                "lingji_agent.execution.tools.fleet_tools.request_fleet_transfer",
                mock_transfer,
            ),
            patch(
                "lingji_agent.execution.tools.fleet_tools.register_lingji_file",
                mock_register,
            ),
            patch(
                "lingji_agent.execution.tools.fleet_tools.fetch_online_agents",
                AsyncMock(return_value=[]),
            ),
        ):
            result = await tool.fn(
                paths=[str(f)],
                to_user_id="user-xyz",
            )

        assert result.get("attachments")
        assert mock_transfer.await_args.kwargs["to_user_id"] == "user-xyz"

    @pytest.mark.asyncio
    async def test_requires_single_destination(self, tmp_path):
        tool = registry.get("fleet_send_file")
        f = tmp_path / "x.txt"
        f.write_text("x", encoding="utf-8")
        result = await tool.fn(paths=[str(f)])
        assert "error" in result
