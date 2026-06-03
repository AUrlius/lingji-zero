import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class StreamingToolParser:
    """流式 JSON 解析器：在 LLM 逐 token 输出过程中实时检测工具调用

    核心策略：
    1. 逐 chunk 累积 token 字符串
    2. 每收到新 token，尝试在累积文本中定位 JSON 对象
    3. 检测 'function' 下的 'name' 和 'arguments' 是否齐全
    4. 齐全时立即标记 ready，允许上层提前 dispatch 工具执行
    5. 兼容思维链文本包围 JSON 的情况
    """

    def __init__(self):
        self._buffer = ""
        self._ready_tool_calls: list[dict[str, Any]] = []
        self._dispatched = False

    def feed(self, chunk: str) -> None:
        self._buffer += chunk
        self._try_extract_tool_calls()

    def is_ready(self) -> bool:
        return len(self._ready_tool_calls) > 0

    def get_tool_call(self) -> dict[str, Any] | None:
        if self._ready_tool_calls:
            tc = self._ready_tool_calls.pop(0)
            if not self._ready_tool_calls:
                self._dispatched = True
            return tc
        return None

    def get_remaining_buffer(self) -> str:
        return self._buffer

    def _try_extract_tool_calls(self) -> None:
        if self._dispatched:
            return

        # 定位 JSON 起始 — prefer array start over single object
        json_start = self._buffer.find('[{"function"')
        if json_start == -1:
            json_start = self._buffer.find('{"function"')
        if json_start == -1:
            return

        segment = self._buffer[json_start:]

        # 尝试逐步扩展右边界解析
        for end_offset in range(len(segment), 0, -1):
            candidate = segment[:end_offset]
            try:
                parsed = json.loads(candidate)
                tool_calls = self._extract_from_parsed(parsed)
                if tool_calls:
                    self._ready_tool_calls = tool_calls
                    return
            except (json.JSONDecodeError, ValueError):
                continue

        # 近似检测：key fields present
        self._try_partial_match(segment)

    def _try_partial_match(self, segment: str) -> None:
        has_name = '"name"' in segment
        has_args = '"arguments"' in segment
        if not (has_name and has_args):
            return

        brace_count = 0
        end_idx = -1
        for i, ch in enumerate(segment):
            if ch == "{":
                brace_count += 1
            elif ch == "}":
                brace_count -= 1
                if brace_count == 0:
                    end_idx = i + 1
                    break

        if end_idx > 0:
            candidate = segment[:end_idx]
            try:
                parsed = json.loads(candidate)
                tool_calls = self._extract_from_parsed(parsed)
                if tool_calls:
                    self._ready_tool_calls = tool_calls
            except (json.JSONDecodeError, ValueError):
                pass

    @staticmethod
    def _extract_from_parsed(parsed: Any) -> list[dict[str, Any]]:
        if isinstance(parsed, dict):
            if "function" in parsed and "name" in parsed.get("function", {}):
                return [{
                    "id": parsed.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": parsed["function"]["name"],
                        "arguments": json.dumps(parsed["function"].get("arguments", {})),
                    },
                }]
        elif isinstance(parsed, list):
            results = []
            for item in parsed:
                if isinstance(item, dict) and "function" in item:
                    results.append({
                        "id": item.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": item["function"].get("name", ""),
                            "arguments": json.dumps(item["function"].get("arguments", {})),
                        },
                    })
            return results
        return []
