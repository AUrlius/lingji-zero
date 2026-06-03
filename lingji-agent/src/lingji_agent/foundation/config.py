"""配置管理 — Pydantic 类型校验 + YAML 加载 + 环境变量覆盖（Sprint 1 T-1.1）"""

import os
from pathlib import Path

import yaml
from pydantic import BaseModel


class NetworkConfig(BaseModel):
    gateway_host: str = "lingji.mygoal.tech"
    gateway_port: int = 443
    device_id: str = "lingji-pc"
    auth_token: str = ""
    reconnect_delay: float = 1.0
    max_reconnect_delay: float = 60.0
    incoming_dir: str = "~/Downloads/LingjiIncoming"


class LLMConfig(BaseModel):
    provider: str = "deepseek"  # deepseek | ollama
    api_key: str = ""
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"


class SecurityConfig(BaseModel):
    hitl_enabled: bool = True
    hitl_timeout_sec: int = 300
    sandbox_image: str = "python:3.11-slim"
    sanitizer_force_docker: bool = True
    guardrails_enabled: bool = True
    guardrails_block: bool = True
    max_execution_time: int = 30
    max_memory_mb: int = 256


class MemoryConfig(BaseModel):
    enabled: bool = True
    db_path: str = "~/.lingji/memory_db"
    episodic_top_k: int = 3
    semantic_top_k: int = 2
    tool_output_max_chars: int = 1000
    decay_enabled: bool = True
    decay_lambda: float = 0.01
    prune_min_weight: float = 0.05
    prune_after_days: int = 30
    summarize_enabled: bool = True
    summarize_min_episodes: int = 30
    summarize_batch_size: int = 20
    summarize_min_age_days: int = 7
    summarize_interval_hours: float = 24.0
    summarize_max_output_chars: int = 2000
    summarize_cold_start_defer: bool = True


class ObservabilityConfig(BaseModel):
    enabled: bool = True
    otlp_endpoint: str = "http://127.0.0.1:4317"
    otlp_insecure: bool = True
    service_name: str = "lingji-agent"
    metrics_enabled: bool = True
    metrics_host: str = "127.0.0.1"
    metrics_port: int = 9091
    trace_log_enabled: bool = True


class AgentConfig(BaseModel):
    network: NetworkConfig = NetworkConfig()
    llm: LLMConfig = LLMConfig()
    security: SecurityConfig = SecurityConfig()
    memory: MemoryConfig = MemoryConfig()
    observability: ObservabilityConfig = ObservabilityConfig()


# ── 环境变量映射 ──────────────────────────────────────────
_ENV_MAP = {
    "LINGJI_GATEWAY_HOST": ("network", "gateway_host"),
    "LINGJI_GATEWAY_PORT": ("network", "gateway_port", int),
    "LINGJI_DEVICE_ID": ("network", "device_id"),
    "LINGJI_AUTH_TOKEN": ("network", "auth_token"),
    "DEEPSEEK_API_KEY": ("llm", "api_key"),
    "LLM_MODEL": ("llm", "model"),
    "LLM_BASE_URL": ("llm", "base_url"),
    "SANDBOX_IMAGE": ("security", "sandbox_image"),
    "LINGJI_HITL_TIMEOUT_SEC": ("security", "hitl_timeout_sec", int),
    "LINGJI_GUARDRAILS_ENABLED": (
        "security",
        "guardrails_enabled",
        lambda v: v.lower() in ("1", "true", "yes"),
    ),
    "LINGJI_GUARDRAILS_BLOCK": (
        "security",
        "guardrails_block",
        lambda v: v.lower() in ("1", "true", "yes"),
    ),
    "LINGJI_MEMORY_ENABLED": ("memory", "enabled", lambda v: v.lower() in ("1", "true", "yes")),
    "LINGJI_MEMORY_DB_PATH": ("memory", "db_path"),
    "LINGJI_MEMORY_SUMMARIZE_ENABLED": (
        "memory",
        "summarize_enabled",
        lambda v: v.lower() in ("1", "true", "yes"),
    ),
    "LINGJI_MEMORY_SUMMARIZE_COLD_START_DEFER": (
        "memory",
        "summarize_cold_start_defer",
        lambda v: v.lower() in ("1", "true", "yes"),
    ),
    "LINGJI_OBSERVABILITY_ENABLED": (
        "observability",
        "enabled",
        lambda v: v.lower() in ("1", "true", "yes"),
    ),
    "LINGJI_OTLP_ENDPOINT": ("observability", "otlp_endpoint"),
    "LINGJI_METRICS_PORT": ("observability", "metrics_port", int),
    "LINGJI_METRICS_ENABLED": (
        "observability",
        "metrics_enabled",
        lambda v: v.lower() in ("1", "true", "yes"),
    ),
}


def load_config(config_path: str | Path | None = None) -> AgentConfig:
    """加载配置：默认值 → YAML 文件 → 环境变量覆盖
    
    优先级：环境变量 > YAML 文件 > 默认值
    """
    config_data: dict = {}

    # 1. 尝试加载 YAML
    if config_path is None:
        config_path = _default_config_path()

    config_path = Path(config_path)
    if config_path.exists():
        with open(config_path) as f:
            config_data = yaml.safe_load(f) or {}

    # 2. Pydantic 解析（应用默认值 + YAML）
    config = AgentConfig.model_validate(config_data)

    # 3. 环境变量覆盖
    for env_var, (section, field, *rest) in _ENV_MAP.items():
        value = os.getenv(env_var)
        if value is not None:
            converter = rest[0] if rest else str
            section_obj = getattr(config, section)
            setattr(section_obj, field, converter(value))

    return config


def _default_config_path() -> Path:
    """查找默认配置文件"""
    candidates = [
        Path("config/default_config.yaml"),
        Path(__file__).resolve().parent.parent.parent / "config" / "default_config.yaml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]
