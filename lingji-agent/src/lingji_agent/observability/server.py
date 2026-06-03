"""Prometheus /metrics HTTP 端点"""

from __future__ import annotations

import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lingji_agent.foundation.config import ObservabilityConfig

logger = logging.getLogger(__name__)

_server: HTTPServer | None = None
_thread: threading.Thread | None = None


class _MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/metrics", "/"):
            self.send_response(404)
            self.end_headers()
            return
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        payload = generate_latest()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPE_LATEST)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        return


def start_metrics_server(config: ObservabilityConfig) -> None:
    global _server, _thread
    if not config.metrics_enabled:
        return
    if _server is not None:
        return
    try:
        _server = HTTPServer((config.metrics_host, config.metrics_port), _MetricsHandler)
        _thread = threading.Thread(
            target=_server.serve_forever,
            name="lingji-metrics",
            daemon=True,
        )
        _thread.start()
        logger.info(
            "Prometheus metrics server http://%s:%d/metrics",
            config.metrics_host,
            config.metrics_port,
        )
    except OSError as exc:
        logger.warning("Prometheus metrics server failed (fail-open): %s", exc)
        _server = None
        _thread = None


def stop_metrics_server() -> None:
    global _server, _thread
    if _server is None:
        return
    _server.shutdown()
    _server.server_close()
    if _thread is not None:
        _thread.join(timeout=2)
    _server = None
    _thread = None
