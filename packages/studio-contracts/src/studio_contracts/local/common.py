from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, AwareDatetime, ConfigDict, Field, StringConstraints

from studio_contracts.common import ContractModel

LOCAL_PROTOCOL_ID = "studio.local"
LOCAL_PROTOCOL_MAJOR = 1
LOCAL_PROTOCOL_MINOR = 0
LOCAL_PROTOCOL_LABEL = f"{LOCAL_PROTOCOL_ID}/v{LOCAL_PROTOCOL_MAJOR}"
LOCAL_CONTRACT_VERSION = 1

MAX_MESSAGE_BYTES = 1_048_576
MAX_METADATA_ENTRIES = 16
MAX_METADATA_VALUE_CHARS = 256
MAX_ERROR_MESSAGE_CHARS = 500
MAX_PAGE_LIMIT = 500
MAX_SEARCH_RESULTS = 100
MAX_READ_BYTES = 262_144


class LocalContractModel(ContractModel):
    """Base of every local (Desktop / bridge / daemon) contract. Strict like the
    server contracts (`extra="forbid"`) and immutable: a peer never receives a
    field it did not negotiate, so additive changes travel behind a capability."""

    model_config = ConfigDict(frozen=True)


_SEMVER_PATTERN = (
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
SemVer = Annotated[str, StringConstraints(pattern=_SEMVER_PATTERN, max_length=64)]
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")]
CapabilityName = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,31}(\.[a-z][a-z0-9_]{0,31}){0,3}$"),
]
CorrelationId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
UtcDatetime = AwareDatetime

_SEMVER_RE = re.compile(_SEMVER_PATTERN)


def semver_tuple(version: str) -> tuple[int, int, int]:
    """Major/minor/patch of a valid SemVer string (pre-release ordering is not
    part of any compatibility decision)."""
    match = _SEMVER_RE.match(version)
    if match is None:
        raise ValueError(f"not a SemVer version: {version!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


_SECRET_VALUE_PATTERNS = (
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{30,}"),
    re.compile(
        r"\b(?:password|passwd|pwd|secret|token|api[_-]?key)\s*[=:]\s*\S{4,}", re.IGNORECASE
    ),
)
_SECRET_KEY_PARTS = (
    "secret",
    "token",
    "password",
    "passwd",
    "private_key",
    "privatekey",
    "api_key",
    "apikey",
    "credential",
    "bearer",
    "authorization",
    "jwt",
    "cookie",
)
_WINDOWS_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
_POSIX_ABSOLUTE_ROOTS = re.compile(
    r"^/(?:home|Users|usr|var|etc|opt|mnt|tmp|root|srv|Volumes|private|data)/"
)
_EMBEDDED_ABSOLUTE_PATH = re.compile(
    r"(?:^|[\s\"'`(),;=:<>\[\]])"
    r"(?:[A-Za-z]:[\\/]|\\\\|~[\\/]|%[A-Za-z_]+%[\\/]|file:/{2,3}"
    r"|/(?:home|Users|usr|var|etc|opt|mnt|tmp|root|srv|Volumes|private|data)/)"
)


def contains_secret_material(text: str) -> bool:
    """Best-effort detection of credential-shaped values (JWT, bearer header,
    provider API keys, private key blocks). Complements — never replaces — the
    structural rule that no contract has a secret-valued field."""
    return any(pattern.search(text) for pattern in _SECRET_VALUE_PATTERNS)


def is_secret_key_name(name: str) -> bool:
    lowered = name.lower().replace("-", "_")
    return any(part in lowered for part in _SECRET_KEY_PARTS)


def looks_like_absolute_path(text: str) -> bool:
    return bool(_WINDOWS_ABSOLUTE.match(text) or _POSIX_ABSOLUTE_ROOTS.match(text))


def contains_absolute_path(text: str) -> bool:
    return looks_like_absolute_path(text) or _EMBEDDED_ABSOLUTE_PATH.search(text) is not None


def _check_safe_text(value: str) -> str:
    if contains_secret_material(value):
        raise ValueError("value looks like credential material")
    if contains_absolute_path(value):
        raise ValueError("value contains an absolute local path")
    return value


def _check_opaque_id(value: str) -> str:
    if contains_secret_material(value):
        raise ValueError("identifier looks like credential material")
    return value


SafeText = Annotated[str, AfterValidator(_check_safe_text)]
OpaqueId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,200}$"),
    AfterValidator(_check_opaque_id),
]
ShortText = Annotated[SafeText, Field(min_length=1, max_length=200)]
MessageText = Annotated[SafeText, Field(min_length=1, max_length=MAX_ERROR_MESSAGE_CHARS)]

MetadataValue = str | int | float | bool | None
_METADATA_KEY_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


def _check_metadata(metadata: dict[str, MetadataValue]) -> dict[str, MetadataValue]:
    if len(metadata) > MAX_METADATA_ENTRIES:
        raise ValueError(f"metadata exceeds {MAX_METADATA_ENTRIES} entries")
    for key, value in metadata.items():
        if _METADATA_KEY_RE.match(key) is None:
            raise ValueError(f"metadata key {key!r} is not a lowercase identifier")
        if is_secret_key_name(key):
            raise ValueError(f"metadata key {key!r} names a secret")
        if isinstance(value, str):
            if len(value) > MAX_METADATA_VALUE_CHARS:
                raise ValueError(f"metadata value for {key!r} exceeds {MAX_METADATA_VALUE_CHARS}")
            if contains_secret_material(value):
                raise ValueError(f"metadata value for {key!r} looks like credential material")
            if contains_absolute_path(value):
                raise ValueError(f"metadata value for {key!r} contains an absolute local path")
    return metadata


BoundedMetadata = Annotated[dict[str, MetadataValue], AfterValidator(_check_metadata)]


def _check_server_origin(value: str) -> str:
    match = re.match(r"^(https?)://([A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])(:\d{1,5})?$", value)
    if match is None:
        raise ValueError("server origin must be scheme://host[:port] without path or credentials")
    if value != value.lower():
        raise ValueError("server origin must be lowercase (normalised)")
    return value


ServerOrigin = Annotated[str, AfterValidator(_check_server_origin)]


def _has_dot_segment(parts: list[str]) -> bool:
    return any(part in (".", "..") for part in parts)


def _check_local_path(value: str) -> str:
    if not value or len(value) > 1024 or "\x00" in value:
        raise ValueError("local path must be 1..1024 characters without NUL")
    if not (_WINDOWS_ABSOLUTE.match(value) or value.startswith("/")):
        raise ValueError("local path must be absolute")
    if _has_dot_segment(re.split(r"[\\/]", value)):
        raise ValueError("local path must be canonical (no '.' or '..' segment)")
    return value


LocalPath = Annotated[str, AfterValidator(_check_local_path)]

_DRIVE_ROOT = re.compile(r"^[A-Za-z]:[\\/]*$")


def _check_workspace_root(value: str) -> str:
    _check_local_path(value)
    if value.startswith("\\\\") or value.startswith("//"):
        raise ValueError("a workspace root cannot be a network (UNC) path")
    if value.strip("/\\") == "" or _DRIVE_ROOT.match(value):
        raise ValueError("a workspace root cannot be a filesystem or drive root")
    return value


WorkspaceRootPath = Annotated[str, AfterValidator(_check_workspace_root)]

_FORBIDDEN_PATH_CHARS = frozenset('?#%:*"<>|')
_INVISIBLE_CONTROL_RANGES = ((0x200B, 0x200F), (0x202A, 0x202E), (0x2066, 0x2069), (0x7F, 0x9F))
_WINDOWS_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)


def _has_invisible_control(value: str) -> bool:
    return any(low <= ord(ch) <= high for ch in value for low, high in _INVISIBLE_CONTROL_RANGES)


def _check_path_segment(part: str) -> None:
    if part != part.strip() or part.endswith("."):
        raise ValueError("path segment must not start or end with a space, or end with a dot")
    if part.split(".", 1)[0].lower() in _WINDOWS_RESERVED_NAMES:
        raise ValueError("path segment uses a reserved device name")


def _check_relative_path(value: str) -> str:
    if not value or len(value) > 512:
        raise ValueError("relative path must be 1..512 characters")
    if "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError("relative path must be POSIX-style, relative and drive-less")
    if (
        any(ord(ch) < 32 for ch in value)
        or _has_invisible_control(value)
        or any(ch in _FORBIDDEN_PATH_CHARS for ch in value)
    ):
        raise ValueError("relative path contains a forbidden character")
    parts = value.split("/")
    if "" in parts or _has_dot_segment(parts):
        raise ValueError("relative path must not contain empty, '.' or '..' segments")
    for part in parts:
        _check_path_segment(part)
    return value


RelativePath = Annotated[str, AfterValidator(_check_relative_path)]


_GLOB_FORBIDDEN_CHARS = frozenset("{}[]~$%")


def _check_glob(value: str) -> str:
    if not value or len(value) > 256:
        raise ValueError("glob must be 1..256 characters")
    if "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError("glob must be POSIX-style, relative and drive-less")
    if any(ord(ch) < 32 for ch in value) or _has_invisible_control(value):
        raise ValueError("glob contains a forbidden character")
    if any(ch in _GLOB_FORBIDDEN_CHARS for ch in value):
        raise ValueError("glob uses an unsupported dialect character")
    if ".." in value.split("/"):
        raise ValueError("glob must not traverse upwards")
    return value


GlobPattern = Annotated[str, AfterValidator(_check_glob)]


class LocalResourceKind(StrEnum):
    KNOWLEDGE = "knowledge"
    CODE = "code"
    HARNESS = "harness"


_URI_RE = re.compile(
    r"^studio-local://(?P<kind>knowledge|code|harness)/"
    r"(?P<workspace>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/"
    r"(?P<path>[^#]*)(?:#(?P<fragment>L\d{1,7}(?:-L\d{1,7})?))?$"
)


def build_local_uri(
    kind: LocalResourceKind,
    workspace_id: UUID,
    relative_path: str,
    *,
    fragment: str | None = None,
) -> str:
    uri = f"studio-local://{kind.value}/{workspace_id}/{relative_path}"
    if fragment:
        uri = f"{uri}#{fragment}"
    parse_local_uri(uri)
    return uri


def parse_local_uri(value: str) -> tuple[LocalResourceKind, UUID, str, str | None]:
    """Split a canonical local resource URI. The URI is workspace-relative by
    construction: it names a resource without ever revealing where the
    workspace lives on this machine."""
    match = _URI_RE.match(value)
    if match is None or len(value) > 700:
        raise ValueError("not a canonical studio-local resource URI")
    path = match.group("path")
    if path:
        _check_relative_path(path)
    return (
        LocalResourceKind(match.group("kind")),
        UUID(match.group("workspace")),
        path,
        match.group("fragment"),
    )


def _check_local_uri(value: str) -> str:
    parse_local_uri(value)
    return value


LocalResourceUri = Annotated[str, AfterValidator(_check_local_uri)]


class ComponentState(StrEnum):
    """Shared state vocabulary of every optional local component (Knowledge,
    Code Graph, harness, watchers). `ready` is the only fully-served state;
    `stale` serves possibly outdated data explicitly; everything else refuses
    or degrades visibly — never silently."""

    DISABLED = "disabled"
    NOT_INSTALLED = "not_installed"
    UNAVAILABLE = "unavailable"
    STARTING = "starting"
    INDEXING = "indexing"
    READY = "ready"
    STALE = "stale"
    PERMISSION_DENIED = "permission_denied"
    INCOMPATIBLE = "incompatible"
    STOPPING = "stopping"
    RECOVERING = "recovering"
    ERROR = "error"


SERVING_STATES = frozenset({ComponentState.READY, ComponentState.STALE})
FAILURE_STATES = frozenset(
    {
        ComponentState.NOT_INSTALLED,
        ComponentState.UNAVAILABLE,
        ComponentState.PERMISSION_DENIED,
        ComponentState.INCOMPATIBLE,
        ComponentState.ERROR,
    }
)


class ComponentId(StrEnum):
    DESKTOP = "desktop"
    BRIDGE = "bridge"
    DAEMON = "daemon"
    WORKSPACE = "workspace"
    KNOWLEDGE = "knowledge"
    CODE_GRAPH = "code_graph"
    HARNESS = "harness"
    SECRET_STORE = "secret_store"
    WATCHER = "watcher"


class LocalErrorCode(StrEnum):
    """Closed, deliberately small taxonomy. Codes describe what the caller can
    branch on; the human message and bounded details carry the rest."""

    INVALID_REQUEST = "invalid_request"
    UNKNOWN_COMMAND = "unknown_command"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    PROTOCOL_INCOMPATIBLE = "protocol_incompatible"
    CAPABILITY_MISSING = "capability_missing"
    NOT_SUPPORTED = "not_supported"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    INTERNAL_ERROR = "internal_error"
    DAEMON_UNAVAILABLE = "daemon_unavailable"
    DAEMON_ALREADY_RUNNING = "daemon_already_running"
    DAEMON_CRASHED = "daemon_crashed"
    IDENTITY_MISMATCH = "identity_mismatch"
    WRONG_PROFILE = "wrong_profile"
    SECRET_ABSENT = "secret_absent"
    SECRET_INACCESSIBLE = "secret_inaccessible"
    SECRET_REVOKED = "secret_revoked"
    KEYRING_UNAVAILABLE = "keyring_unavailable"
    WORKSPACE_CONFIG_MISSING = "workspace_config_missing"
    WORKSPACE_CONFIG_INVALID = "workspace_config_invalid"
    WORKSPACE_MOVED = "workspace_moved"
    WORKSPACE_INACCESSIBLE = "workspace_inaccessible"
    PROJECT_UNAVAILABLE = "project_unavailable"
    FEATURE_DISABLED = "feature_disabled"
    PROVIDER_NOT_INSTALLED = "provider_not_installed"
    PROVIDER_INCOMPATIBLE = "provider_incompatible"
    PERMISSION_DENIED = "permission_denied"
    INDEX_ABSENT = "index_absent"
    INDEX_CORRUPT = "index_corrupt"
    LANGUAGE_UNSUPPORTED = "language_unsupported"
    PLAN_EXPIRED = "plan_expired"


class LocalError(LocalContractModel):
    """The one structured error shape of the local stack. Never carries a
    secret, a stack trace or an absolute local path: `message` and `details`
    are validated, bounded and safe to display or log."""

    code: LocalErrorCode
    message: MessageText
    component: ComponentId
    retryable: bool
    details: BoundedMetadata = {}
    correlation_id: CorrelationId | None = None
