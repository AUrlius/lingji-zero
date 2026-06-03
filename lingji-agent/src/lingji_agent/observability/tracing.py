"""OpenTelemetry 链路追踪 — Sprint 11 子集"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator
from urllib.parse import urlparse

if TYPE_CHECKING:
    from lingji_agent.foundation.config import ObservabilityConfig

logger = logging.getLogger(__name__)

_tracer = None
_enabled = False


def is_tracing_enabled() -> bool:
    return _enabled and _tracer is not None


def init_tracing(config: ObservabilityConfig) -> None:
    global _tracer, _enabled
    if not config.enabled:
        return
    if _enabled:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        endpoint = config.otlp_endpoint
        parsed = urlparse(endpoint)
        otlp_endpoint = parsed.netloc or parsed.path or endpoint
        if otlp_endpoint.startswith("http://"):
            otlp_endpoint = otlp_endpoint[len("http://") :]
        elif otlp_endpoint.startswith("https://"):
            otlp_endpoint = otlp_endpoint[len("https://") :]

        resource = Resource.create({"service.name": config.service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(
            endpoint=otlp_endpoint,
            insecure=config.otlp_insecure,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(config.service_name)
        _enabled = True
        logger.info(
            "OTel tracing enabled service=%s endpoint=%s",
            config.service_name,
            otlp_endpoint,
        )
    except Exception as exc:
        logger.warning("OTel tracing init failed (fail-open): %s", exc)


def shutdown_tracing() -> None:
    global _tracer, _enabled
    if not _enabled:
        return
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        shutdown = getattr(provider, "shutdown", None)
        if callable(shutdown):
            shutdown()
    except Exception as exc:
        logger.warning("OTel tracing shutdown: %s", exc)
    _tracer = None
    _enabled = False


@contextmanager
def trace_span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    if not is_tracing_enabled():
        yield None
        return
    attrs = attributes or {}
    with _tracer.start_as_current_span(name, attributes=attrs) as span:
        yield span


def add_span_event(name: str, attributes: dict[str, Any] | None = None) -> None:
    if not is_tracing_enabled():
        return
    from opentelemetry import trace

    span = trace.get_current_span()
    if span and span.is_recording():
        span.add_event(name, attributes=attributes or {})
