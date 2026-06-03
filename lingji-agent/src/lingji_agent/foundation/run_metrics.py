"""进程内运行指标 — 二期可观测 Lite + Prometheus 双写（4.2）"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SUMMARY_INTERVAL = 50

_COUNTERS: dict[str, int] = {
    "cmd_total": 0,
    "hitl_interrupt_total": 0,
    "hitl_timeout_total": 0,
    "agent_errors": 0,
    "run_complete_total": 0,
    "guardrail_blocked_total": 0,
    "upload_saved_total": 0,
    "upload_fastpath_total": 0,
}

_PROMETHEUS_MAP = {
    "cmd_total": "cmd_total",
    "hitl_interrupt_total": "hitl_interrupt_total",
    "hitl_timeout_total": "hitl_timeout_total",
    "agent_errors": "agent_errors_total",
    "run_complete_total": "run_complete_total",
    "guardrail_blocked_total": "guardrail_blocked_total",
    "upload_saved_total": "upload_saved_total",
    "upload_fastpath_total": "upload_fastpath_total",
}


def increment(name: str, amount: int = 1, **labels: str) -> None:
    _COUNTERS[name] = _COUNTERS.get(name, 0) + amount
    if name == "cmd_total" and _COUNTERS["cmd_total"] % _SUMMARY_INTERVAL == 0:
        log_summary()
    _prometheus_inc(name, amount, **labels)


def _prometheus_inc(name: str, amount: int, **labels: str) -> None:
    prom_name = _PROMETHEUS_MAP.get(name)
    if prom_name is None:
        return
    try:
        from lingji_agent.observability import metrics as prom_metrics

        if name == "guardrail_blocked_total":
            prom_metrics.inc_counter(
                prom_name,
                amount,
                rule_id=labels.get("rule_id") or "unknown",
            )
        else:
            prom_metrics.inc_counter(prom_name, amount)
    except Exception:
        pass


def record_run_duration(seconds: float) -> None:
    try:
        from lingji_agent.observability import metrics as prom_metrics

        prom_metrics.record_run_duration(seconds)
    except Exception:
        pass


def snapshot() -> dict[str, int]:
    return dict(_COUNTERS)


def log_summary() -> None:
    logger.info(
        "metrics_summary cmd_total=%d hitl_interrupt=%d hitl_timeout=%d "
        "agent_errors=%d run_complete=%d guardrail_blocked=%d "
        "upload_saved=%d upload_fastpath=%d",
        _COUNTERS.get("cmd_total", 0),
        _COUNTERS.get("hitl_interrupt_total", 0),
        _COUNTERS.get("hitl_timeout_total", 0),
        _COUNTERS.get("agent_errors", 0),
        _COUNTERS.get("run_complete_total", 0),
        _COUNTERS.get("guardrail_blocked_total", 0),
        _COUNTERS.get("upload_saved_total", 0),
        _COUNTERS.get("upload_fastpath_total", 0),
    )


def reset_for_tests() -> None:
    for key in _COUNTERS:
        _COUNTERS[key] = 0
