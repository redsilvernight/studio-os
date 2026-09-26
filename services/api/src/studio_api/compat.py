from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from studio_contracts.version import (
    CLIENT_FAMILIES,
    CLIENT_STATUS_CURRENT,
    CLIENT_STATUS_RECOMMENDED,
)

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


def client_status(client: str | None, client_version: str | None, settings: object) -> str:
    """Advisory verdict for a supported (or undeclared) client.

    `recommended` means the declared build is served but a newer release
    exists (grace window: still fully functional, only a non-blocking
    nudge). Anything unreadable/undeclared is `current` — silence, never a
    false alarm. The mandatory case is not represented here: it is the 426.
    """
    if not client or client.lower() not in CLIENT_FAMILIES or not client_version:
        return CLIENT_STATUS_CURRENT
    family = client.lower()
    latest = family_latest(settings, family)
    minimum = family_minimum(settings, family)
    if not latest:
        return CLIENT_STATUS_CURRENT
    parsed = parse_version(client_version)
    newest = parse_version(latest)
    if parsed is None or newest is None:
        return CLIENT_STATUS_CURRENT
    if is_supported(client_version, minimum) and parsed < newest:
        return CLIENT_STATUS_RECOMMENDED
    return CLIENT_STATUS_CURRENT
