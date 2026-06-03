import pytest
import json
from lingji_agent.cognitive.streaming_parser import StreamingToolParser


class TestStreamingToolParser:
    def test_buffer_accumulates_tokens(self):
        p = StreamingToolParser()
        assert not p.is_ready()
        p.feed('{"function": {"name": "read_file", "arguments": {"path": "/tmp/test.txt"}}}')
        assert p.is_ready()
        result = p.get_tool_call()
        assert result is not None
        assert result["function"]["name"] == "read_file"

    def test_handles_text_before_json(self):
        p = StreamingToolParser()
        p.feed("Let me read that file for you.\n")
        assert not p.is_ready()
        p.feed('{"function": {"name": "read_file", "arguments": {"path": "/etc/hosts"}}}')
        assert p.is_ready()

    def test_returns_none_when_incomplete(self):
        p = StreamingToolParser()
        p.feed('{"function": {"name": "read_')
        assert not p.is_ready()
        assert p.get_tool_call() is None

    def test_resets_after_get(self):
        p = StreamingToolParser()
        p.feed('{"function": {"name": "ls", "arguments": {}}}')
        assert p.is_ready()
        p.get_tool_call()
        assert not p.is_ready()
        assert p.get_tool_call() is None

    def test_multiple_tool_calls_in_stream(self):
        p = StreamingToolParser()
        p.feed('[{"function": {"name": "ls", "arguments": {}}}, {"function": {"name": "pwd", "arguments": {}}}]')
        calls = []
        tc = p.get_tool_call()
        while tc:
            calls.append(tc)
            tc = p.get_tool_call()
        assert len(calls) == 2
        assert calls[0]["function"]["name"] == "ls"
        assert calls[1]["function"]["name"] == "pwd"
