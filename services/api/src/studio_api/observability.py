"""Observability metrics and structured logging configuration."""

from __future__ import annotations

import json
import logging
import sys
import time

from fastapi import Request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from studio_api.security_log import SECURITY_EVENT_ATTR, RedactingFilter

logger = logging.getLogger(__name__)

REGISTRY = CollectorRegistry(auto_describe=True)

REQUEST_COUNT = Counter(
    "studio_api_http_requests_total",
    "Total HTTP requests",
    ["method", "status", "path"],
    registry=REGISTRY,
)

REQUEST_DURATION = Histogram(
    "studio_api_http_request_duration_seconds",
    "HTTP request duration",
    ["method", "path"],
    registry=REGISTRY,
)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record Prometheus metrics for every request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        status = str(response.status_code)
        method = request.method
        path = request.url.path
        REQUEST_COUNT.labels(method=method, status=status, path=path).inc()
        REQUEST_DURATION.labels(method=method, path=path).observe(duration)
        return response


def metrics_response() -> Response:
    """Generate the Prometheus /metrics payload."""
    return Response(
        content=generate_latest(REGISTRY),
        media_type=CONTENT_TYPE_LATEST,
    )


class JsonFormatter(logging.Formatter):
    """Structured JSON log formatter for production."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "request_id"):
            payload["request_id"] = record.request_id
        if hasattr(record, SECURITY_EVENT_ATTR):
            payload[SECURITY_EVENT_ATTR] = getattr(record, SECURITY_EVENT_ATTR)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(log_format: str = "text", log_level: str = "INFO") -> None:
    """Configure root logging for the API process."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    if log_format.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
