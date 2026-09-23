from __future__ import annotations

import logging
import os
from collections.abc import MutableMapping
from urllib.parse import urlsplit

from pydantic import ValidationError

from studio_client.config import ClientConfig

_LOGGER = logging.getLogger("studio_client.daemon.desktop_origin")

DESKTOP_ORIGIN_ENV = "STUDIO_DESKTOP_SERVER_ORIGIN"
TOKEN_ENV = "STUDIO_CLIENT_MACHINE_TOKEN"
TOKEN_ORIGIN_ENV = "STUDIO_CLIENT_MACHINE_TOKEN_ORIGIN"

_MAX_LENGTH = 2048
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1"}
_DESKTOP_HOSTS = {"tauri.localhost", "ipc.localhost", "tauri"}
_DEFAULT_PORTS = {"http": 80, "https": 443}


class DesktopOriginError(ValueError):
    pass


def validate_desktop_origin(raw: str) -> str:
    value = raw.strip()
    if not value or len(value) > _MAX_LENGTH:
        raise DesktopOriginError("invalid desktop server origin")
    if any(char.isspace() or not char.isprintable() or char == "*" for char in value):
        raise DesktopOriginError("invalid desktop server origin")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as exc:
        raise DesktopOriginError("invalid desktop server origin") from exc
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in {"http", "https"} or not host:
        raise DesktopOriginError("desktop server origin must be an http(s) origin")
    if parts.username is not None or parts.password is not None:
        raise DesktopOriginError("desktop server origin must not carry credentials")
    if parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise DesktopOriginError("desktop server origin must not carry a path")
    if host.rstrip(".") in _DESKTOP_HOSTS:
        raise DesktopOriginError("desktop server origin must not be the desktop shell origin")
    if scheme == "http" and host not in _LOOPBACK_HOSTS:
        raise DesktopOriginError("plain http is only accepted for local development")
    authority = f"[{host}]" if ":" in host else host
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        authority = f"{authority}:{port}"
    return f"{scheme}://{authority}"


def _configured_origin() -> str | None:
    try:
        configured = ClientConfig()  # type: ignore[call-arg]
    except ValidationError:
        return None
    parts = urlsplit(configured.api_base_url)
    if not parts.scheme or not parts.netloc:
        return None
    try:
        return validate_desktop_origin(f"{parts.scheme}://{parts.netloc}")
    except DesktopOriginError:
        return None


def bind_env_token(
    origin: str, configured_origin: str | None, env: MutableMapping[str, str]
) -> None:
    if not env.get(TOKEN_ENV):
        return
    if env.get(TOKEN_ORIGIN_ENV):
        return
    if configured_origin == origin:
        env[TOKEN_ORIGIN_ENV] = origin
        return
    _LOGGER.warning("ignoring an unbound machine token env override for the desktop origin")
    del env[TOKEN_ENV]


def desktop_client_config() -> ClientConfig | None:
    raw = os.environ.get(DESKTOP_ORIGIN_ENV)
    if raw is None:
        return None
    origin = validate_desktop_origin(raw)
    bind_env_token(origin, _configured_origin(), os.environ)
    return ClientConfig(api_base_url=origin)
