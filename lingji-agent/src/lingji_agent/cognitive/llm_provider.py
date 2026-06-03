"""LLM 连接器抽象接口（Sprint 2 T-2.3）

ILLMConnector: 切换 DeepSeek/Ollama 只需换一行实现类
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


# ── 抽象接口 ──────────────────────────────────────────────

class ILLMConnector(ABC):
    """LLM 连接器抽象接口"""

    @abstractmethod
    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """返回统一格式：{content, tool_calls, model, usage}"""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...


# ── DeepSeek 实现 ─────────────────────────────────────────

class DeepSeekConnector(ILLMConnector):
    """DeepSeek API 实现（带重试 + 错误处理）"""

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com",
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._client = None

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def client(self):
        """延迟初始化 OpenAI 客户端（复用连接）"""
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                max_retries=0,  # 我们自己控制重试
            )
        return self._client

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """调用 DeepSeek API，带指数退避重试"""
        last_error = None
        for attempt in range(self.max_retries):
            try:
                return await self._call(messages, tools, stream=stream)
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2 ** attempt)
                    logger.warning(
                        "DeepSeek API 调用失败 (attempt %d/%d): %s — %ss 后重试",
                        attempt + 1, self.max_retries, e, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "DeepSeek API 调用最终失败 (attempt %d/%d): %s",
                        attempt + 1, self.max_retries, e,
                    )

        raise RuntimeError(
            f"DeepSeek API 调用失败（{self.max_retries} 次尝试）: {last_error}"
        )

    async def _call(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """单次 API 调用"""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        if stream:
            return await self._call_streaming(kwargs)
        else:
            response = await self.client.chat.completions.create(**kwargs)
            choice = response.choices[0].message

            return {
                "content": choice.content or "",
                "tool_calls": _normalize_tool_calls(choice.tool_calls),
                "model": response.model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                },
            }

    async def _call_streaming(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """流式调用 + StreamingToolParser 提前检测"""
        from lingji_agent.cognitive.streaming_parser import StreamingToolParser

        kwargs["stream"] = True
        stream = await self.client.chat.completions.create(**kwargs)

        content_parts: list[str] = []
        pending_calls: dict[int, dict[str, Any]] = {}  # index → {name, args_fragments}
        model_name = ""
        usage = {}

        async for chunk in stream:
            if chunk.model:
                model_name = chunk.model
            if chunk.usage:
                usage = {
                    "prompt_tokens": chunk.usage.prompt_tokens,
                    "completion_tokens": chunk.usage.completion_tokens,
                    "total_tokens": chunk.usage.total_tokens,
                }

            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            if delta.content:
                content_parts.append(delta.content)

            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index if hasattr(tc_delta, 'index') else 0
                    func = tc_delta.function if hasattr(tc_delta, 'function') else None
                    if func is None:
                        continue

                    if idx not in pending_calls:
                        pending_calls[idx] = {"name": "", "args_parts": [], "id": ""}

                    if hasattr(tc_delta, 'id') and tc_delta.id:
                        pending_calls[idx]["id"] = tc_delta.id
                    if hasattr(func, 'name') and func.name:
                        pending_calls[idx]["name"] = func.name
                    if hasattr(func, 'arguments') and func.arguments:
                        pending_calls[idx]["args_parts"].append(func.arguments)

        full_content = "".join(content_parts)

        # Build final tool_calls from accumulated deltas
        tool_calls = []
        for idx in sorted(pending_calls.keys()):
            call = pending_calls[idx]
            if call["name"]:
                tool_calls.append({
                    "id": call["id"] or "",
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": "".join(call["args_parts"]),
                    },
                })

        logger.info(
            "[streaming] 流式响应完成: content_len=%d, tool_calls=%d",
            len(full_content), len(tool_calls),
        )

        return {
            "content": full_content,
            "tool_calls": tool_calls,
            "model": model_name,
            "usage": usage,
            "streamed": True,
        }


# ── Ollama 实现（预留骨架）─────────────────────────────────

class OllamaConnector(ILLMConnector):
    """Ollama 本地模型 — 预留骨架"""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:14b",
    ):
        self.base_url = base_url
        self.model = model

    @property
    def model_name(self) -> str:
        return self.model

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "OllamaConnector 尚未实现。计划在 Windows 适配阶段填充。"
        )


# ── Factory ───────────────────────────────────────────────

def create_connector(config) -> ILLMConnector:
    """根据配置创建 LLM 连接器"""
    from lingji_agent.foundation.config import AgentConfig

    if isinstance(config, AgentConfig):
        llm_cfg = config.llm
    else:
        llm_cfg = config

    if llm_cfg.provider == "ollama":
        return OllamaConnector(
            base_url=llm_cfg.base_url,
            model=llm_cfg.model,
        )
    else:
        return DeepSeekConnector(
            api_key=llm_cfg.api_key,
            model=llm_cfg.model,
            base_url=llm_cfg.base_url,
        )


# ── Helpers ───────────────────────────────────────────────

def _normalize_tool_calls(tool_calls) -> list[dict[str, Any]]:
    """标准化 tool_calls 为统一格式"""
    if not tool_calls:
        return []
    result = []
    for tc in tool_calls:
        result.append({
            "id": getattr(tc, "id", ""),
            "type": "function",
            "function": {
                "name": tc.function.name if hasattr(tc, "function") else "",
                "arguments": tc.function.arguments if hasattr(tc, "function") else "{}",
            },
        })
    return result
