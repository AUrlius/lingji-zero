"""Fleet 4.0d — 调度 Agent ID 解析（Job 台账 scheduler_agent_id）"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lingji_agent.foundation.config import AgentConfig

_bound: AgentConfig | None = None


def bind_scheduler_config(config: AgentConfig) -> None:
    """main 启动时绑定；供 job/fleet 工具读取 scheduler_agent_id。"""
    global _bound
    _bound = config


def get_scheduler_agent_id(*, fallback_device_id: str = "") -> str:
    """返回写入 Job 的 scheduler_agent_id。

    优先级：YAML scheduler_agent_id → env LINGJI_SCHEDULER_AGENT_ID
    → scheduler.enabled 时本机 device_id → fallback_device_id → lingji-laptop。
    """
    env = (os.getenv("LINGJI_SCHEDULER_AGENT_ID") or "").strip()
    if _bound is not None:
        sch = (_bound.scheduler.scheduler_agent_id or "").strip()
        if sch:
            return sch
        if env:
            return env
        if _bound.scheduler.enabled:
            return _bound.network.device_id
    if env:
        return env
    if fallback_device_id:
        return fallback_device_id
    return (os.getenv("LINGJI_DEVICE_ID") or "").strip() or "lingji-laptop"


def is_scheduler_agent(device_id: str | None = None) -> bool:
    """本机是否为调度 Agent（对用户负责的那一面）。"""
    if _bound is None:
        return False
    did = (device_id or _bound.network.device_id or "").strip()
    if not _bound.scheduler.enabled:
        return False
    sch = get_scheduler_agent_id(fallback_device_id=did)
    return did == sch
