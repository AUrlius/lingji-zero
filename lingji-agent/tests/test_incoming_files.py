"""G6.2 — 手机上传落盘"""

import pytest

from lingji_agent.network.incoming_files import (
    sanitize_filename,
    save_uploads_to_pc,
    _resolve_dest_under_base,
    text_implies_file_organization,
    uploads_all_saved,
    format_saved_reply,
    format_upload_errors,
    validate_incoming_dir_config,
)
from pathlib import Path


class TestSanitizeFilename:
    def test_strips_unsafe_chars(self):
        assert sanitize_filename("hello world.txt") == "hello_world.txt"

    def test_empty_becomes_upload(self):
        assert sanitize_filename("   ") == "upload"

    def test_rejects_dotdot(self):
        assert sanitize_filename("..") == "upload"
        assert sanitize_filename("../secret.jpg") == "secret.jpg"
        assert sanitize_filename("../../etc/passwd") == "passwd"

    def test_uses_basename_only(self):
        assert sanitize_filename("/var/tmp/photo.jpg") == "photo.jpg"


class TestUploadHelpers:
    def test_organization_intent_with_path(self):
        assert text_implies_file_organization("放到 ~/Downloads/LingjiIncoming/test/")
        assert text_implies_file_organization("移到 LingjiIncoming/test 文件夹")

    def test_uploads_all_saved(self):
        assert uploads_all_saved([{"path": "/a"}], 1)
        assert not uploads_all_saved([{"error": "x"}], 1)

    def test_format_saved_reply(self):
        text = format_saved_reply([{"name": "a.jpg", "path": "/tmp/a.jpg"}])
        assert "a.jpg" in text
        assert "/tmp/a.jpg" in text

    def test_format_upload_errors(self):
        text = format_upload_errors([{"name": "x", "error": "fail"}])
        assert "fail" in text

    def test_validate_incoming_dir_rejects_downloads_root(self, tmp_path, monkeypatch):
        downloads = tmp_path / "Downloads"
        downloads.mkdir()
        monkeypatch.setattr("lingji_agent.network.incoming_files.Path.home", lambda: tmp_path)
        with pytest.raises(ValueError, match="LingjiIncoming"):
            validate_incoming_dir_config(str(downloads))


class TestResolveDestUnderBase:
    def test_rejects_traversal(self, tmp_path):
        base = tmp_path / "LingjiIncoming"
        base.mkdir()
        assert _resolve_dest_under_base(base, "..") is None

    def test_accepts_normal_file(self, tmp_path):
        base = tmp_path / "LingjiIncoming"
        base.mkdir()
        dest = _resolve_dest_under_base(base, "photo.jpg")
        assert dest is not None
        assert dest.parent == base.resolve()


@pytest.mark.asyncio
async def test_save_uploads_to_pc_mock_download(monkeypatch, tmp_path):
    from lingji_agent.network import incoming_files as mod

    async def fake_download(**kwargs):
        dest = kwargs["dest_path"]
        dest.write_bytes(b"payload")
        return {"path": str(dest), "size_bytes": 7}

    monkeypatch.setattr(mod, "download_file_from_gateway", fake_download)

    block, results = await mod.save_uploads_to_pc(
        [{"file_id": "f1", "name": "photo.jpg", "download_path": "/files/f1?token=t"}],
        incoming_dir=str(tmp_path),
        gateway_host="127.0.0.1",
        gateway_port=8765,
        auth_token="secret",
    )
    assert "photo.jpg" in block
    assert results[0]["path"]
    assert (tmp_path / "photo.jpg").read_bytes() == b"payload"


@pytest.mark.asyncio
async def test_save_uploads_rejects_traversal(monkeypatch, tmp_path):
    from lingji_agent.network import incoming_files as mod

    async def fake_download(**kwargs):
        raise AssertionError("should not download traversal names")

    monkeypatch.setattr(mod, "download_file_from_gateway", fake_download)

    incoming = tmp_path / "LingjiIncoming"
    incoming.mkdir()
    monkeypatch.setattr(mod, "sanitize_filename", lambda n: "..")

    block, results = await mod.save_uploads_to_pc(
        [{"file_id": "f1", "name": "..", "download_path": "/files/f1?token=t"}],
        incoming_dir=str(incoming),
        gateway_host="127.0.0.1",
        gateway_port=8765,
        auth_token="secret",
    )
    assert "失败" in block or "非法" in block
    assert results[0].get("error")
    assert not list(incoming.iterdir())
    assert not list(incoming.parent.glob("*.*"))


@pytest.mark.asyncio
async def test_execute_command_blocks_gateway_redownload():
    from lingji_agent.execution.tools.sys_tools import execute_command_tool

    result = await execute_command_tool(
        "curl -o ~/Downloads/x.jpg https://lingji.mygoal.tech/files/abc?token=t"
    )
    assert result.get("error")
    assert "move_file" in result["error"]
