"""Structlog 与 OTel trace_id 绑定"""

from __future__ import annotations

from opentelemetry import trace


def add_trace_id(_logger, _method_name, event_dict):
    span = trace.get_current_span()
    if span and span.get_span_context().is_valid:
        ctx = span.get_span_context()
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict
