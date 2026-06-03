"""可观测性单元测试 — 四期 4.2"""

import socket

import pytest

from lingji_agent.foundation.config import ObservabilityConfig
from lingji_agent.foundation import run_metrics
from lingji_agent.observability import metrics as prom_metrics
from lingji_agent.observability import server as metrics_server
from lingji_agent.observability import tracing
from lingji_agent.observability.setup import init_observability, shutdown_observability


@pytest.fixture
def disabled_obs():
    cfg = ObservabilityConfig(enabled=False, metrics_enabled=False)
    yield cfg
    shutdown_observability()
    prom_metrics.reset_for_tests()
    tracing.shutdown_tracing()


@pytest.fixture
def metrics_only_cfg():
    cfg = ObservabilityConfig(
        enabled=False,
        metrics_enabled=True,
        metrics_port=19091,
    )
    yield cfg
    shutdown_observability()
    prom_metrics.reset_for_tests()


class TestObservabilityDisabled:
    def test_init_does_not_enable_tracing(self, disabled_obs):
        init_observability(disabled_obs)
        assert not tracing.is_tracing_enabled()

    def test_trace_span_noop(self, disabled_obs):
        init_observability(disabled_obs)
        with tracing.trace_span("test.span") as span:
            assert span is None


class TestPrometheusMetrics:
    def test_run_metrics_dual_write(self, metrics_only_cfg):
        init_observability(metrics_only_cfg)
        run_metrics.reset_for_tests()
        run_metrics.increment("cmd_total")
        run_metrics.increment("guardrail_blocked_total", rule_id="inj.test")
        run_metrics.record_run_duration(1.5)
        assert run_metrics.snapshot()["cmd_total"] == 1
        assert prom_metrics.is_metrics_enabled()

    def test_record_llm_usage(self, metrics_only_cfg):
        init_observability(metrics_only_cfg)
        prom_metrics.record_llm_usage(
            "mock-model",
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )


class TestMetricsServer:
    def test_metrics_server_exposes_endpoint(self, metrics_only_cfg):
        init_observability(metrics_only_cfg)
        run_metrics.increment("cmd_total")
        sock = socket.create_connection(
            (metrics_only_cfg.metrics_host, metrics_only_cfg.metrics_port),
            timeout=2,
        )
        sock.sendall(b"GET /metrics HTTP/1.1\r\nHost: localhost\r\n\r\n")
        chunks: list[bytes] = []
        while True:
            part = sock.recv(4096)
            if not part:
                break
            chunks.append(part)
        sock.close()
        data = b"".join(chunks)
        assert b"lingji_cmd_total" in data
