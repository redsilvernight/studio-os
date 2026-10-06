"""Fast, local-only probe of the services the infra-bound tests need.

A bare TCP connect with a short timeout: no query, no external network. The
hosts/ports come from the same settings the tests use, so the probe answers
"would the fixture be able to connect", not "is something on a default port".
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://studio:studio@127.0.0.1:5432/studio_os_test"
DEFAULT_S3_ENDPOINT_URL = "http://localhost:9000"
PROBE_TIMEOUT_SECONDS = 0.5

SERVICES = ("postgres", "minio")


@dataclass(frozen=True)
class ProbeResult:
    service: str
    host: str
    port: int
    reachable: bool


def _tcp_open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _postgres_target() -> tuple[str, int]:
    parts = urlsplit(os.environ.get("STUDIO_TEST_DATABASE_URL") or DEFAULT_TEST_DATABASE_URL)
    return parts.hostname or "127.0.0.1", parts.port or 5432


def _minio_target() -> tuple[str, int]:
    parts = urlsplit(os.environ.get("STUDIO_S3_ENDPOINT_URL") or DEFAULT_S3_ENDPOINT_URL)
    default_port = 443 if parts.scheme == "https" else 80
    return parts.hostname or "127.0.0.1", parts.port or default_port


def probe(service: str, timeout: float = PROBE_TIMEOUT_SECONDS) -> ProbeResult:
    host, port = _postgres_target() if service == "postgres" else _minio_target()
    return ProbeResult(service, host, port, _tcp_open(host, port, timeout))


def probe_all(timeout: float = PROBE_TIMEOUT_SECONDS) -> dict[str, ProbeResult]:
    return {service: probe(service, timeout) for service in SERVICES}


if __name__ == "__main__":
    results = probe_all()
    for result in results.values():
        state = "up" if result.reachable else "DOWN"
        print(f"{result.service}: {state} ({result.host}:{result.port})")
    raise SystemExit(0 if all(r.reachable for r in results.values()) else 1)
