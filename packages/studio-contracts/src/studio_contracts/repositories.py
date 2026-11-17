from __future__ import annotations

import re
from urllib.parse import urlsplit

_ALLOWED_SCHEMES = frozenset({"https", "http", "ssh"})
_HOST_RE = re.compile(r"^[a-z0-9_.-]+$")
_SEGMENT_RE = re.compile(r"^[a-z0-9_.-]+$")
_SCP_RE = re.compile(r"^(?P<user>[^@/\s:]+)@(?P<host>[^@/\s:]+):(?P<path>.+)$")


def _clean_path(path: str) -> list[str]:
    text = path.strip().strip("/")
    if text.lower().endswith(".git"):
        text = text[: -len(".git")].strip("/")
    return [segment.lower() for segment in text.split("/") if segment]


def _check_host(host: str) -> str:
    name = host.strip().lower()
    if not _HOST_RE.match(name):
        raise ValueError(f"invalid repository host: {host!r}")
    return name


def _build(host: str, segments: list[str]) -> str:
    if len(segments) != 2 or any(
        segment in {".", ".."} or not _SEGMENT_RE.match(segment) for segment in segments
    ):
        raise ValueError(f"invalid repository path: {'/'.join(segments)!r}")
    return f"{host}/{segments[0]}/{segments[1]}"


def normalize_remote_url(url: str) -> str:
    if not isinstance(url, str):
        raise ValueError(f"invalid remote URL: {url!r}")
    text = url.strip()
    if not text:
        raise ValueError("invalid remote URL: empty")
    if "://" in text:
        try:
            parts = urlsplit(text)
        except ValueError as exc:
            raise ValueError(f"invalid remote URL: {url!r}") from exc
        if parts.scheme.lower() not in _ALLOWED_SCHEMES:
            raise ValueError(f"unsupported remote URL scheme: {url!r}")
        if not parts.hostname:
            raise ValueError(f"invalid remote URL: {url!r}")
        return _build(_check_host(parts.hostname), _clean_path(parts.path))
    match = _SCP_RE.match(text)
    if match is None:
        raise ValueError(f"invalid remote URL: {url!r}")
    return _build(_check_host(match.group("host")), _clean_path(match.group("path")))
