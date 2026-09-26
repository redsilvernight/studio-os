from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from studio_contracts.version import CLIENT_FAMILIES

try:
    SERVER_VERSION: str = version("studio-api")
except PackageNotFoundError:  # pragma: no cover - editable/src layouts without metadata
    SERVER_VERSION = "0.1.0"


def parse_version(raw: str | None) -> tuple[int, ...] | None:
    """Numeric dotted prefix of a client version, or None when unreadable.

    Pre-release (`1.2.3-rc.1`) and build (`1.2.3+4`) suffixes never affect
    the compatibility verdict. Unreadable input answers None so the
    caller passes the request through instead of blocking it.
    """
    if not raw:
        return None
    core = raw.strip().split("+", 1)[0].split("-", 1)[0]
    parts = core.split(".")
    if not parts:
        return None
    numbers: list[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        numbers.append(int(part))
    return tuple(numbers)


def is_supported(client_version: str | None, minimum: str | None) -> bool:
    """True unless the client declares a version strictly below the minimum.

    Missing, unknown-family or unparsable versions always pass: old clients
    that predate the negotiation headers keep working untouched.
    """
    if not client_version or not minimum:
        return True
    parsed = parse_version(client_version)
    floor = parse_version(minimum)
    if parsed is None or floor is None:
        return True
    width = max(len(parsed), len(floor))
    padded = parsed + (0,) * (width - len(parsed))
    padded_floor = floor + (0,) * (width - len(floor))
    return padded >= padded_floor


def family_minimum(settings: object, family: str) -> str | None:
    return getattr(settings, f"{family}_minimum_version", None)


def family_latest(settings: object, family: str) -> str | None:
    return getattr(settings, f"{family}_latest_version", None)


def check_client(client: str | None, client_version: str | None, settings: object) -> bool:
    """Single verdict used by the middleware guard."""
    if not client or client.lower() not in CLIENT_FAMILIES:
        return True
    return is_supported(client_version, family_minimum(settings, client.lower()))
