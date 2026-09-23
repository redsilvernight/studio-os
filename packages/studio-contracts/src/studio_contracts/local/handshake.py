from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from studio_contracts.local.common import (
    LOCAL_PROTOCOL_ID,
    LOCAL_PROTOCOL_MAJOR,
    CapabilityName,
    ComponentId,
    ComponentState,
    CorrelationId,
    LocalContractModel,
    LocalError,
    LocalErrorCode,
    SemVer,
    ServerOrigin,
)


class ProtocolVersion(LocalContractModel):
    major: int = Field(ge=1, le=999)
    minor: int = Field(ge=0, le=999)

    def as_tuple(self) -> tuple[int, int]:
        return (self.major, self.minor)


class ProtocolRange(LocalContractModel):
    minimum: ProtocolVersion
    maximum: ProtocolVersion

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.minimum.as_tuple() > self.maximum.as_tuple():
            raise ValueError("protocol range minimum exceeds maximum")
        return self


class PeerRole(StrEnum):
    DESKTOP = "desktop"
    DAEMON = "daemon"


class OptionalComponentStatus(LocalContractModel):
    """An optional component as the daemon sees it at handshake time. Its
    absence never breaks compatibility; it degrades exactly the capabilities
    that depend on it."""

    component: ComponentId
    state: ComponentState
    provider_id: str | None = Field(default=None, max_length=64)
    provides: list[CapabilityName] = []


class PeerInfo(LocalContractModel):
    """One side of the handshake. `component_version` is informational and
    never enters a compatibility decision: only the protocol range and the
    capability sets do."""

    role: PeerRole
    protocol_id: str = Field(default=LOCAL_PROTOCOL_ID, max_length=32)
    protocol: ProtocolRange
    component_version: SemVer
    server_origin: ServerOrigin | None = None
    capabilities: list[CapabilityName] = Field(default=[], max_length=128)
    required_capabilities: list[CapabilityName] = Field(default=[], max_length=64)
    optional_capabilities: list[CapabilityName] = Field(default=[], max_length=64)
    optional_components: list[OptionalComponentStatus] = []

    @model_validator(mode="after")
    def _unique(self) -> Self:
        for name in ("capabilities", "required_capabilities", "optional_capabilities"):
            values = getattr(self, name)
            if len(set(values)) != len(values):
                raise ValueError(f"{name} contains duplicates")
        return self


class HandshakeRequest(LocalContractModel):
    peer: PeerInfo


class CompatibilityOutcome(StrEnum):
    COMPATIBLE = "compatible"
    COMPATIBLE_DEGRADED = "compatible_degraded"
    DAEMON_TOO_OLD = "daemon_too_old"
    DESKTOP_TOO_OLD = "desktop_too_old"
    CAPABILITY_MISSING = "capability_missing"
    PROTOCOL_INCOMPATIBLE = "protocol_incompatible"


COMPATIBLE_OUTCOMES = frozenset(
    {CompatibilityOutcome.COMPATIBLE, CompatibilityOutcome.COMPATIBLE_DEGRADED}
)


class Remediation(StrEnum):
    NONE = "none"
    UPDATE_DAEMON = "update_daemon"
    UPDATE_DESKTOP = "update_desktop"
    INSTALL_OPTIONAL_COMPONENT = "install_optional_component"
    ENABLE_FEATURE = "enable_feature"
    REPORT_PROBLEM = "report_problem"


class DegradedFeature(LocalContractModel):
    capability: CapabilityName
    component: ComponentId
    state: ComponentState


class HandshakeResponse(LocalContractModel):
    """Outcome of the negotiation. Failure is terminal and fail-closed: no
    capability is granted and there is no fallback protocol — the caller shows
    `remediation`, it does not retry with a lower level."""

    outcome: CompatibilityOutcome
    daemon: PeerInfo
    negotiated: ProtocolVersion | None = None
    granted_capabilities: list[CapabilityName] = []
    missing_required: list[CapabilityName] = []
    missing_optional: list[CapabilityName] = []
    degraded: list[DegradedFeature] = []
    remediation: Remediation = Remediation.NONE
    error: LocalError | None = None
    silent_fallback: Literal[False] = False

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.outcome in COMPATIBLE_OUTCOMES:
            if self.negotiated is None or self.error is not None or self.missing_required:
                raise ValueError("a compatible outcome negotiates a version and reports no error")
            if self.outcome is CompatibilityOutcome.COMPATIBLE and (
                self.degraded or self.missing_optional
            ):
                raise ValueError("compatible outcome cannot be degraded")
            if self.outcome is CompatibilityOutcome.COMPATIBLE_DEGRADED and not (
                self.degraded or self.missing_optional
            ):
                raise ValueError("degraded outcome must name what is degraded")
            return self
        if self.negotiated is not None or self.granted_capabilities:
            raise ValueError("an incompatible outcome grants nothing")
        if self.error is None:
            raise ValueError("an incompatible outcome carries a structured error")
        if self.remediation is Remediation.NONE:
            raise ValueError("an incompatible outcome names a remediation")
        return self


_OUTCOME_ERROR: dict[CompatibilityOutcome, tuple[LocalErrorCode, Remediation]] = {
    CompatibilityOutcome.DAEMON_TOO_OLD: (
        LocalErrorCode.PROTOCOL_INCOMPATIBLE,
        Remediation.UPDATE_DAEMON,
    ),
    CompatibilityOutcome.DESKTOP_TOO_OLD: (
        LocalErrorCode.PROTOCOL_INCOMPATIBLE,
        Remediation.UPDATE_DESKTOP,
    ),
    CompatibilityOutcome.PROTOCOL_INCOMPATIBLE: (
        LocalErrorCode.PROTOCOL_INCOMPATIBLE,
        Remediation.REPORT_PROBLEM,
    ),
    CompatibilityOutcome.CAPABILITY_MISSING: (
        LocalErrorCode.CAPABILITY_MISSING,
        Remediation.UPDATE_DAEMON,
    ),
}


def _refuse(
    correlation_id: CorrelationId | None,
    daemon: PeerInfo,
    outcome: CompatibilityOutcome,
    message: str,
    *,
    missing_required: list[str] | None = None,
    remediation: Remediation | None = None,
) -> HandshakeResponse:
    code, default_remediation = _OUTCOME_ERROR[outcome]
    return HandshakeResponse(
        outcome=outcome,
        daemon=daemon,
        missing_required=sorted(missing_required or []),
        remediation=remediation or default_remediation,
        error=LocalError(
            code=code,
            message=message,
            component=ComponentId.DAEMON,
            retryable=False,
            correlation_id=correlation_id,
        ),
    )


def negotiate(
    request: HandshakeRequest, daemon: PeerInfo, *, correlation_id: CorrelationId | None = None
) -> HandshakeResponse:
    """Reference compatibility decision, deterministic and side-effect free.
    Every implementation (daemon, Desktop, mocks) must agree with it."""
    desktop = request.peer
    if (
        desktop.role is not PeerRole.DESKTOP
        or daemon.role is not PeerRole.DAEMON
        or desktop.protocol_id != LOCAL_PROTOCOL_ID
        or daemon.protocol_id != LOCAL_PROTOCOL_ID
    ):
        return _refuse(
            correlation_id,
            daemon,
            CompatibilityOutcome.PROTOCOL_INCOMPATIBLE,
            "The peers do not speak the same local protocol.",
        )
    if desktop.protocol.maximum.as_tuple() < daemon.protocol.minimum.as_tuple():
        return _refuse(
            correlation_id,
            daemon,
            CompatibilityOutcome.DESKTOP_TOO_OLD,
            "The Desktop is older than the oldest protocol this daemon accepts.",
        )
    if daemon.protocol.maximum.as_tuple() < desktop.protocol.minimum.as_tuple():
        return _refuse(
            correlation_id,
            daemon,
            CompatibilityOutcome.DAEMON_TOO_OLD,
            "The daemon is older than the oldest protocol this Desktop accepts.",
        )
    negotiated = min(desktop.protocol.maximum, daemon.protocol.maximum, key=lambda v: v.as_tuple())
    if negotiated.major != LOCAL_PROTOCOL_MAJOR:
        return _refuse(
            correlation_id,
            daemon,
            CompatibilityOutcome.PROTOCOL_INCOMPATIBLE,
            "The negotiated protocol major version is not implemented by this contract.",
        )

    unserved: dict[str, OptionalComponentStatus] = {
        capability: component
        for component in daemon.optional_components
        if component.state not in (ComponentState.READY, ComponentState.STALE)
        for capability in component.provides
    }
    daemon_offer = set(daemon.capabilities) - set(unserved)
    desktop_offer = set(desktop.capabilities)
    missing_on_daemon = set(desktop.required_capabilities) - daemon_offer
    missing_on_desktop = set(daemon.required_capabilities) - desktop_offer
    if missing_on_daemon or missing_on_desktop:
        if missing_on_daemon:
            remediation = (
                Remediation.INSTALL_OPTIONAL_COMPONENT
                if missing_on_daemon <= set(unserved)
                else Remediation.UPDATE_DAEMON
            )
        else:
            remediation = Remediation.UPDATE_DESKTOP
        return _refuse(
            correlation_id,
            daemon,
            CompatibilityOutcome.CAPABILITY_MISSING,
            "A capability required by one peer is not offered by the other.",
            missing_required=list(missing_on_daemon | missing_on_desktop),
            remediation=remediation,
        )

    granted = sorted(daemon_offer & desktop_offer)
    wanted_optional = set(desktop.optional_capabilities)
    degraded = [
        DegradedFeature(capability=capability, component=component.component, state=component.state)
        for capability, component in sorted(unserved.items())
        if capability in wanted_optional or capability in desktop_offer
    ]
    degraded_caps = {item.capability for item in degraded}
    missing_optional = sorted(wanted_optional - daemon_offer - degraded_caps)
    outcome = (
        CompatibilityOutcome.COMPATIBLE_DEGRADED
        if degraded or missing_optional
        else CompatibilityOutcome.COMPATIBLE
    )
    return HandshakeResponse(
        outcome=outcome,
        daemon=daemon,
        negotiated=negotiated,
        granted_capabilities=granted,
        missing_optional=missing_optional,
        degraded=degraded,
        remediation=(
            Remediation.INSTALL_OPTIONAL_COMPONENT
            if outcome is CompatibilityOutcome.COMPATIBLE_DEGRADED
            else Remediation.NONE
        ),
    )
