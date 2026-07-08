"""配置模块单元测试"""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from lingji_agent.foundation.config import (
    AgentConfig,
    NetworkConfig,
    LLMConfig,
    SecurityConfig,
    SchedulerConfig,
    load_config,
)


class TestConfigDefaults:
    def test_default_network(self):
        cfg = AgentConfig()
        assert cfg.network.gateway_host == "lingji.mygoal.tech"
        assert cfg.network.gateway_port == 443
        assert cfg.network.device_id == "lingji-pc"

    def test_default_llm(self):
        cfg = AgentConfig()
        assert cfg.llm.provider == "deepseek"
        assert cfg.llm.model == "deepseek-chat"

    def test_default_security(self):
        cfg = AgentConfig()
        assert cfg.security.hitl_enabled is True
        assert cfg.security.hitl_timeout_sec == 300
        assert cfg.security.max_execution_time == 30

    def test_default_scheduler(self):
        cfg = AgentConfig()
        assert cfg.scheduler.enabled is False
        assert cfg.scheduler.scheduler_agent_id == ""
        assert cfg.scheduler.guardian_executor_ids == []


class TestYamlLoading:
    def test_load_from_yaml(self):
        yaml_data = {
            "network": {
                "gateway_host": "192.168.1.1",
                "gateway_port": 9999,
                "device_id": "test-pc",
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(yaml_data, f)
            path = f.name

        try:
            cfg = load_config(path)
            assert cfg.network.gateway_host == "192.168.1.1"
            assert cfg.network.gateway_port == 9999
            assert cfg.network.device_id == "test-pc"
        finally:
            os.unlink(path)

    def test_yaml_partial_override(self):
        """YAML 只覆盖部分字段，其余用默认值"""
        yaml_data = {"network": {"device_id": "custom-pc"}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(yaml_data, f)
            path = f.name

        try:
            cfg = load_config(path)
            assert cfg.network.device_id == "custom-pc"
            assert cfg.network.gateway_port == 443  # 默认值
        finally:
            os.unlink(path)

    def test_scheduler_yaml(self):
        yaml_data = {
            "scheduler": {
                "enabled": True,
                "scheduler_agent_id": "lingji-laptop",
                "guardian_executor_ids": ["lingji-pc"],
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(yaml_data, f)
            path = f.name
        try:
            cfg = load_config(path)
            assert cfg.scheduler.enabled is True
            assert cfg.scheduler.scheduler_agent_id == "lingji-laptop"
            assert cfg.scheduler.guardian_executor_ids == ["lingji-pc"]
        finally:
            os.unlink(path)

    def test_empty_yaml(self):
        """空 YAML 文件 —— 全部默认"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            path = f.name

        try:
            cfg = load_config(path)
            assert cfg.network.gateway_port == 443
        finally:
            os.unlink(path)


class TestEnvOverride:
    def test_env_overrides_yaml(self):
        yaml_data = {"network": {"device_id": "from-yaml"}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(yaml_data, f)
            path = f.name

        try:
            os.environ["LINGJI_DEVICE_ID"] = "from-env"
            cfg = load_config(path)
            assert cfg.network.device_id == "from-env"
        finally:
            os.unlink(path)
            del os.environ["LINGJI_DEVICE_ID"]

    def test_env_port_override(self):
        os.environ["LINGJI_GATEWAY_PORT"] = "12345"
        try:
            cfg = load_config()
            assert cfg.network.gateway_port == 12345
        finally:
            del os.environ["LINGJI_GATEWAY_PORT"]

    def test_env_api_key(self):
        os.environ["DEEPSEEK_API_KEY"] = "sk-test-123"
        try:
            cfg = load_config()
            assert cfg.llm.api_key == "sk-test-123"
        finally:
            del os.environ["DEEPSEEK_API_KEY"]
