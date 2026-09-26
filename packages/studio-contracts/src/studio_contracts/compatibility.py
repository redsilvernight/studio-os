"""Reference version & compatibility policy (DU-0/D, B2).

Pure, deterministic, dependency-free: the single source of truth for the
``current / latest / minimum_supported`` policy and the N/N-1 compatibility
matrix. Enforcement (``GET /api/v1/meta/compatibility``, client gating) is a
C1 concern and must agree with this module — never the reverse.

Version vocabulary (each version has exactly one canonical source):

- ``desktop_version`` — ``desktop/package.json`` (bundle source of truth).
- ``server_version`` — the deployed server release (exposed by C1; no code
  constant yet, the release train is the reference).
- ``api_contract_version`` — ``studio_contracts.API_CONTRACT_VERSION``.
- ``event_schema_version`` — ``studio_contracts.EVENT_SCHEMA_VERSION``.
- ``local_protocol_version`` — ``studio_contracts.local`` major/minor.
"""

from __future__ import annotations

from enum import StrEnum

from studio_contracts import API_CONTRACT_VERSION, EVENT_SCHEMA_VERSION
from studio_contracts.local.common import (
    LOCAL_PROTOCOL_MAJOR,
    LOCAL_PROTOCOL_MINOR,
)

SUPPORTED_LAG = 1
"""Release-train lag accepted by a server N: N (lag 0) and N-1 (lag 1)."""

CHANNELS = ("beta", "stable")
"""Distribution channels; each publishes its own ``latest`` manifest (B5)."""

REBUILD_NEVER_TRUSTED = True
"""A rebuild of the same tag is never the same artefact: only the artefact
promoted by manifest (same hash + signatures, DU-0/E) is trusted."""


class ChangeKind(StrEnum):
    ADDITIVE = "additive"
    API_BREAKING = "api_breaking"
    EVENT_BREAKING = "event_breaking"
    LOCAL_BREAKING = "local_breaking"
    AUTH_BREAKING = "auth_breaking"


class ClientVerdict(StrEnum):
    COMPATIBLE = "compatible"
    UPGRADE_RECOMMENDED = "upgrade_recommended"
    UPGRADE_REQUIRED = "upgrade_required"
    PROTOCOL_INCOMPATIBLE = "protocol_incompatible"


_LAG_N = "N"
_LAG_N_MINUS_1 = "N-1"
_LAG_OLDER = "<N-1"


def _lag_band(lag: int) -> str:
    if lag <= 0:
        return _LAG_N
    if lag == 1:
        return _LAG_N_MINUS_1
    return _LAG_OLDER


COMPATIBILITY_MATRIX: dict[tuple[ChangeKind, str], ClientVerdict] = {
    (ChangeKind.ADDITIVE, _LAG_N): ClientVerdict.COMPATIBLE,
    (ChangeKind.ADDITIVE, _LAG_N_MINUS_1): ClientVerdict.UPGRADE_RECOMMENDED,
    (ChangeKind.ADDITIVE, _LAG_OLDER): ClientVerdict.UPGRADE_REQUIRED,
    (ChangeKind.API_BREAKING, _LAG_N): ClientVerdict.COMPATIBLE,
    (ChangeKind.API_BREAKING, _LAG_N_MINUS_1): ClientVerdict.UPGRADE_REQUIRED,
    (ChangeKind.API_BREAKING, _LAG_OLDER): ClientVerdict.UPGRADE_REQUIRED,
    (ChangeKind.EVENT_BREAKING, _LAG_N): ClientVerdict.COMPATIBLE,
    (ChangeKind.EVENT_BREAKING, _LAG_N_MINUS_1): ClientVerdict.UPGRADE_REQUIRED,
    (ChangeKind.EVENT_BREAKING, _LAG_OLDER): ClientVerdict.UPGRADE_REQUIRED,
    (ChangeKind.LOCAL_BREAKING, _LAG_N): ClientVerdict.COMPATIBLE,
    (ChangeKind.LOCAL_BREAKING, _LAG_N_MINUS_1): ClientVerdict.PROTOCOL_INCOMPATIBLE,
    (ChangeKind.LOCAL_BREAKING, _LAG_OLDER): ClientVerdict.PROTOCOL_INCOMPATIBLE,
    (ChangeKind.AUTH_BREAKING, _LAG_N): ClientVerdict.COMPATIBLE,
    (ChangeKind.AUTH_BREAKING, _LAG_N_MINUS_1): ClientVerdict.UPGRADE_REQUIRED,
    (ChangeKind.AUTH_BREAKING, _LAG_OLDER): ClientVerdict.UPGRADE_REQUIRED,
}


def classify(change: ChangeKind, lag: int, *, same_artifact: bool = True) -> ClientVerdict:
    """Verdict for a client ``lag`` releases behind server N.

    ``lag`` 0 is N, 1 is N-1, >= 2 is older. ``same_artifact=False`` means the
    bytes are not the manifest-promoted artefact (a rebuild): untrusted,
    always refused however recent. A breaking change ships with N, so a client
    at N is always compatible; anything else fails closed before any mutation.
    """
    if not same_artifact and REBUILD_NEVER_TRUSTED:
        return ClientVerdict.PROTOCOL_INCOMPATIBLE
    return COMPATIBILITY_MATRIX[(change, _lag_band(lag))]


CURRENT_VERSIONS = {
    "api_contract_version": API_CONTRACT_VERSION,
    "event_schema_version": EVENT_SCHEMA_VERSION,
    "local_protocol_major": LOCAL_PROTOCOL_MAJOR,
    "local_protocol_minor": LOCAL_PROTOCOL_MINOR,
}
