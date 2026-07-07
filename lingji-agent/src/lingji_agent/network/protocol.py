"""WS 消息协议模型（Sprint 1 T-1.2 + G6 attachments）

6 种消息类型：AUTH_REQ, HEARTBEAT, CMD_TEXT, HITL_REQ, HITL_RES, AGENT_RES
AGENT_RES.payload 可含 attachments[]（G6 远程文件下载）
AGENT_RES.payload.status=activity 时为运行阶段指示（非聊天）：phase=thinking|tool|waiting_hitl|idle
"""

import json
import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FileAttachment(BaseModel):
    """AGENT_RES.payload.attachments[] 单条附件（与 Gateway /files 对齐）"""

    file_id: str
    name: str
    size_bytes: int
    mime: str = "application/octet-stream"
    download_path: str


class MsgType(str, Enum):
    AUTH_REQ = "AUTH_REQ"
    HEARTBEAT = "HEARTBEAT"
    CMD_TEXT = "CMD_TEXT"
    CMD_LIST_SESSIONS = "CMD_LIST_SESSIONS"
    HITL_REQ = "HITL_REQ"
    HITL_RES = "HITL_RES"
    AGENT_RES = "AGENT_RES"
    FLEET_DELIVER = "FLEET_DELIVER"
    FLEET_ACK = "FLEET_ACK"
    FLEET_RELAY_BY_ID = "FLEET_RELAY_BY_ID"


class Message(BaseModel):
    msg_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    msg_type: MsgType
    device_id: str
    timestamp: float = Field(default_factory=time.time)
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, data: str) -> "Message":
        # Python json.loads 比 Pydantic 更宽容 Unicode 转义
        # Go 的 json.Marshal 对 emoji 等字符使用 \udXXX 代理对
        obj = json.loads(data)
        # 清洗代理对字符——json.loads 保留它们但 UTF-8 不支持
        obj = _sanitize_surrogates(obj)
        return cls.model_validate(obj)


def _sanitize_surrogates(obj):
    """递归清理对象中的 lone surrogate 字符"""
    if isinstance(obj, str):
        return obj.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")
    elif isinstance(obj, dict):
        return {k: _sanitize_surrogates(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_surrogates(v) for v in obj]
    return obj


def parse_message(raw: str) -> Message:
    """多态反序列化：根据 msg_type 字段分派"""
    return Message.from_json(raw)


def build_agent_res_payload(
    text: str,
    attachments: list[FileAttachment | dict[str, Any]] | None = None,
    *,
    target_device_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """构造 AGENT_RES.payload（text + 可选 attachments + target_device_id 定向 Web 端）"""
    payload: dict[str, Any] = {"text": text, **extra}
    if target_device_id:
        payload["target_device_id"] = target_device_id
    if attachments:
        payload["attachments"] = [
            a.model_dump() if isinstance(a, FileAttachment) else a for a in attachments
        ]
    return payload


def parse_attachments(payload: dict[str, Any]) -> list[FileAttachment]:
    """从 AGENT_RES.payload 解析 attachments"""
    raw = payload.get("attachments") or []
    return [FileAttachment.model_validate(item) for item in raw]
