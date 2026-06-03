"""错误码体系（LLDD）"""

from enum import IntEnum


class ErrorCode(IntEnum):
    OK = 0
    NETWORK_ERROR = 1001
    AUTH_FAILED = 1002
    LLM_TIMEOUT = 2001
    LLM_PARSE_ERROR = 2002
    TOOL_NOT_FOUND = 3001
    SANDBOX_ERROR = 3002
    HITL_TIMEOUT = 4001
    HITL_REJECTED = 4002
    UNKNOWN = 9999


class LingjiError(Exception):
    def __init__(self, code: ErrorCode, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code.name}] {message}")
