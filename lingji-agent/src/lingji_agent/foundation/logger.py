"""结构化日志 — structlog + stdlib 集成（Sprint 1 T-1.1）"""

import logging
import os

import structlog

from lingji_agent.observability.logging_bridge import add_trace_id


def setup_logging(level: str = "INFO", *, trace_log: bool = False):
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )

    processors = [
        structlog.contextvars.merge_contextvars,
    ]
    if trace_log:
        processors.append(add_trace_id)
    processors.extend(
        [
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)


def get_logger(name: str):
    return structlog.get_logger(name)
