"""Prometheus 业务指标 — Sprint 11 子集"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lingji_agent.foundation.config import ObservabilityConfig

logger = logging.getLogger(__name__)

_enabled = False

_COUNTERS: dict[str, Any] = {}
_HISTOGRAMS: dict[str, Any] = {}


def _counter(name: str, doc: str, labelnames: tuple[str, ...] = ()):
    from prometheus_client import Counter

    return Counter(name, doc, labelnames=labelnames)


def _histogram(name: str, doc: str):
    from prometheus_client import Histogram

    return Histogram(name, doc, buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300))


def init_metrics(config: ObservabilityConfig) -> None:
    global _enabled
    if not config.metrics_enabled:
        return
    if _enabled:
        return
    _COUNTERS["cmd_total"] = _counter("lingji_cmd_total", "Total CMD_TEXT received")
    _COUNTERS["run_complete_total"] = _counter(
        "lingji_run_complete_total", "Completed agent runs"
    )
    _COUNTERS["agent_errors_total"] = _counter(
        "lingji_agent_errors_total", "Agent execution errors"
    )
    _COUNTERS["hitl_interrupt_total"] = _counter(
        "lingji_hitl_interrupt_total", "HITL interrupt events"
    )
    _COUNTERS["hitl_timeout_total"] = _counter(
        "lingji_hitl_timeout_total", "HITL approval timeouts"
    )
    _COUNTERS["guardrail_blocked_total"] = _counter(
        "lingji_guardrail_blocked_total",
        "Requests blocked by guardrails",
        labelnames=("rule_id",),
    )
    _COUNTERS["upload_saved_total"] = _counter(
        "lingji_upload_saved_total",
        "Phone/Web uploads saved to incoming_dir",
    )
    _COUNTERS["upload_fastpath_total"] = _counter(
        "lingji_upload_fastpath_total",
        "Upload CMD_TEXT handled without LLM (no organize intent)",
    )
    _COUNTERS["llm_tokens_total"] = _counter(
        "lingji_llm_tokens_total",
        "LLM token usage",
        labelnames=("model", "type"),
    )
    _HISTOGRAMS["run_duration_seconds"] = _histogram(
        "lingji_run_duration_seconds", "Agent run duration in seconds"
    )
    _enabled = True
    logger.info("Prometheus metrics registered")


def is_metrics_enabled() -> bool:
    return _enabled


def inc_counter(name: str, amount: int = 1, **labels: str) -> None:
    if not _enabled:
        return
    counter = _COUNTERS.get(name)
    if counter is None:
        return
    if labels:
        counter.labels(**labels).inc(amount)
    else:
        counter.inc(amount)


def record_run_duration(seconds: float) -> None:
    if not _enabled:
        return
    hist = _HISTOGRAMS.get("run_duration_seconds")
    if hist is not None:
        hist.observe(seconds)


def record_llm_usage(model: str, usage: dict[str, Any]) -> None:
    if not _enabled or not usage:
        return
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    if prompt:
        inc_counter("llm_tokens_total", prompt, model=model, type="prompt")
    if completion:
        inc_counter("llm_tokens_total", completion, model=model, type="completion")


def reset_for_tests() -> None:
    global _enabled
    from prometheus_client import REGISTRY

    for collector in list(_COUNTERS.values()) + list(_HISTOGRAMS.values()):
        try:
            REGISTRY.unregister(collector)
        except KeyError:
            pass
    _COUNTERS.clear()
    _HISTOGRAMS.clear()
    _enabled = False
