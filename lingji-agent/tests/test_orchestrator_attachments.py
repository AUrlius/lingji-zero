"""G6 format_response attachments 保留测试"""

import json

from lingji_agent.cognitive.orchestrator import format_response


def test_format_response_keeps_attachments_in_state():
    state = {
        "final_response": "ok",
        "messages": [],
        "tool_results": [
            {
                "tool_name": "send_file_to_user",
                "result": json.dumps(
                    {
                        "attachments": [
                            {
                                "file_id": "x",
                                "name": "a.txt",
                                "size_bytes": 1,
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
    assert len(out.get("attachments", [])) == 1
    assert out["attachments"][0]["file_id"] == "x"
