"""Fleet 4.0d — scheduler_agent_id 解析"""

import os

import pytest

from lingji_agent.foundation.config import AgentConfig, SchedulerConfig
from lingji_agent.foundation.scheduler import (
    bind_scheduler_config,
    get_scheduler_agent_id,
    is_scheduler_agent,
)


@pytest.fixture(autouse=True)
def _reset_bind():
    bind_scheduler_config(AgentConfig())
    yield
    bind_scheduler_config(AgentConfig())


class TestSchedulerAgentId:
    def test_laptop_scheduler_enabled_uses_device_id(self):
        cfg = AgentConfig(
            network=AgentConfig().network.model_copy(update={"device_id": "lingji-laptop"}),
            scheduler=SchedulerConfig(enabled=True, scheduler_agent_id=""),
        )
        bind_scheduler_config(cfg)
        assert get_scheduler_agent_id() == "lingji-laptop"
        assert is_scheduler_agent()

    def test_explicit_scheduler_agent_id(self):
        cfg = AgentConfig(
            network=AgentConfig().network.model_copy(update={"device_id": "lingji-pc"}),
            scheduler=SchedulerConfig(
                enabled=False,
                scheduler_agent_id="lingji-laptop",
            ),
        )
        bind_scheduler_config(cfg)
        assert get_scheduler_agent_id() == "lingji-laptop"
        assert not is_scheduler_agent()

    def test_env_override_when_not_in_yaml(self):
        cfg = AgentConfig(
            scheduler=SchedulerConfig(enabled=False, scheduler_agent_id=""),
        )
        bind_scheduler_config(cfg)
        os.environ["LINGJI_SCHEDULER_AGENT_ID"] = "lingji-laptop"
        try:
            assert get_scheduler_agent_id() == "lingji-laptop"
        finally:
            del os.environ["LINGJI_SCHEDULER_AGENT_ID"]

    def test_fallback_default(self):
        assert get_scheduler_agent_id() == "lingji-laptop"
