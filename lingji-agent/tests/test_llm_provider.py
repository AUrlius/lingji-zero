"""LLM Provider 单元测试"""

import pytest

from lingji_agent.cognitive.llm_provider import (
    ILLMConnector,
    DeepSeekConnector,
    OllamaConnector,
    create_connector,
    _normalize_tool_calls,
)
from lingji_agent.foundation.config import AgentConfig, LLMConfig


class TestDeepSeekConnector:
    def test_init_defaults(self):
        conn = DeepSeekConnector(api_key="sk-test")
        assert conn.model == "deepseek-chat"
        assert conn.base_url == "https://api.deepseek.com"
        assert conn.max_retries == 3

    def test_init_custom(self):
        conn = DeepSeekConnector(
            api_key="sk-test",
            model="deepseek-reasoner",
            base_url="https://custom.api.com",
            max_retries=5,
            retry_delay=2.0,
        )
        assert conn.model == "deepseek-reasoner"
        assert conn.max_retries == 5

    def test_model_name(self):
        conn = DeepSeekConnector(api_key="sk-test")
        assert conn.model_name == "deepseek-chat"

    def test_client_lazy_init(self):
        conn = DeepSeekConnector(api_key="sk-test")
        assert conn._client is None  # 延迟初始化

    def test_abstract_interface(self):
        """验证 ILLMConnector 是抽象类"""
        with pytest.raises(TypeError):
            ILLMConnector()  # type: ignore


class TestOllamaConnector:
    def test_init_defaults(self):
        conn = OllamaConnector()
        assert conn.model == "qwen2.5:14b"
        assert conn.base_url == "http://localhost:11434"

    def test_not_implemented(self):
        conn = OllamaConnector()
        with pytest.raises(NotImplementedError, match="尚未实现"):
            import asyncio
            asyncio.run(conn.chat_completion([{"role": "user", "content": "hi"}]))


class TestCreateConnector:
    def test_creates_deepseek_by_default(self):
        conn = create_connector(LLMConfig(provider="deepseek", api_key="sk-test"))
        assert isinstance(conn, DeepSeekConnector)

    def test_creates_ollama(self):
        conn = create_connector(LLMConfig(provider="ollama"))
        assert isinstance(conn, OllamaConnector)

    def test_from_agent_config(self):
        cfg = AgentConfig()
        cfg.llm.api_key = "sk-test"
        conn = create_connector(cfg)
        assert isinstance(conn, DeepSeekConnector)


class TestNormalizeToolCalls:
    def test_none(self):
        assert _normalize_tool_calls(None) == []

    def test_empty_list(self):
        assert _normalize_tool_calls([]) == []
