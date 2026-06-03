"""可观测性一键初始化"""

from __future__ import annotations

import logging

from lingji_agent.foundation.config import ObservabilityConfig
from lingji_agent.observability import metrics, server, tracing

logger = logging.getLogger(__name__)


def init_observability(config: ObservabilityConfig) -> None:
    tracing.init_tracing(config)
    metrics.init_metrics(config)
    server.start_metrics_server(config)
    if config.enabled and not tracing.is_tracing_enabled():
        logger.warning(
            "observability: OTel 未就绪（Collector 未起？），Agent 仍正常连 Gateway"
        )


def shutdown_observability() -> None:
    server.stop_metrics_server()
    tracing.shutdown_tracing()
    metrics.reset_for_tests()
