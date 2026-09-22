from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import Field, TypeAdapter, model_validator

from studio_contracts.local.code_graph import (
    CodeGraphStatus,
    CodeReindexRequest,
    CodeReindexResult,
    CodeSymbolQuery,
    CodeSymbolResult,
)
from studio_contracts.local.common import (
    MAX_MESSAGE_BYTES,
    ComponentId,
    ComponentState,
    CorrelationId,
    Identifier,
    LocalContractModel,
    LocalError,
    LocalErrorCode,
    OpaqueId,
    ShortText,
    UtcDatetime,
)
from studio_contracts.local.daemon_control import (
    DaemonAction,
    DaemonControlRequest,
    DaemonControlResult,
    DaemonHealth,
    DaemonHealthRequest,
    DaemonStatus,
)
from studio_contracts.local.graph import GraphExpandRequest, GraphPage, GraphPageRequest
from studio_contracts.local.handshake import HandshakeRequest, HandshakeResponse
from studio_contracts.local.harness import (
    HarnessApplyRequest,
    HarnessApplyResult,
    HarnessDetectResult,
    HarnessPlan,
    HarnessPreviewRequest,
    HarnessRollbackRequest,
    HarnessRollbackResult,
    HarnessStatus,
    HarnessStatusRequest,
)
from studio_contracts.local.identity import IdentityView
from studio_contracts.local.knowledge import (
    KnowledgeDocument,
    KnowledgeGetDocumentRequest,
    KnowledgeReindexRequest,
    KnowledgeReindexResult,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    KnowledgeStatus,
)
from studio_contracts.local.publication import (
    PublicationPlan,
    PublicationPreviewRequest,
    PublicationPublishRequest,
    PublicationResult,
)
from studio_contracts.local.workspace import (
    LocalWorkspaceConfig,
    WorkspaceConfirmRootsRequest,
    WorkspaceConfirmRootsResult,
    WorkspaceGetConfigRequest,
    WorkspaceGitStatus,
    WorkspaceSaveConfigRequest,
    WorkspaceScope,
    WorkspaceStatus,
    WorkspaceValidateRequest,
)

DEFAULT_REQUEST_LIMIT_BYTES = 65_536
DEFAULT_TIMEOUT_MS = 30_000
LONG_TIMEOUT_MS = 300_000

FORBIDDEN_PRIMITIVE_TERMS = (
    "exec",
    "shell",
    "spawn",
    "process",
    "filesystem",
    "fs.",
    "http",
    "proxy",
    "eval",
    "raw",
    "stdin",
    "command_line",
)


class EmptyPayload(LocalContractModel):
    pass


class BridgeCommand(StrEnum):
    """The complete, closed set of things the Desktop may ask the local side to
    do. Adding a command is a contract change; nothing outside this list is
    reachable, and no member executes user-supplied code, touches an arbitrary
    path, spawns a process or forwards a network request."""

    RUNTIME_HANDSHAKE = "runtime.handshake"
    DAEMON_STATUS = "daemon.status"
    DAEMON_ATTACH = "daemon.attach"
    DAEMON_START = "daemon.start"
    DAEMON_STOP = "daemon.stop"
    DAEMON_RESTART = "daemon.restart"
    DAEMON_HEALTH = "daemon.health"
    IDENTITY_GET_VIEW = "identity.get_view"
    WORKSPACE_VALIDATE = "workspace.validate"
    WORKSPACE_GET_CONFIG = "workspace.get_config"
    WORKSPACE_CONFIRM_ROOTS = "workspace.confirm_roots"
    WORKSPACE_GIT_STATUS = "workspace.git_status"
    WORKSPACE_SAVE_CONFIG = "workspace.save_config"
    KNOWLEDGE_STATUS = "knowledge.status"
    KNOWLEDGE_SEARCH = "knowledge.search"
    KNOWLEDGE_GET_DOCUMENT = "knowledge.get_document"
    KNOWLEDGE_GRAPH_PAGE = "knowledge.graph_page"
    KNOWLEDGE_GRAPH_EXPAND = "knowledge.graph_expand"
    KNOWLEDGE_REINDEX = "knowledge.reindex"
    CODE_GRAPH_STATUS = "code_graph.status"
    CODE_GRAPH_FIND_SYMBOLS = "code_graph.find_symbols"
    CODE_GRAPH_GRAPH_PAGE = "code_graph.graph_page"
    CODE_GRAPH_GRAPH_EXPAND = "code_graph.graph_expand"
    CODE_GRAPH_REINDEX = "code_graph.reindex"
    HARNESS_DETECT = "harness.detect"
    HARNESS_STATUS = "harness.status"
    HARNESS_PREVIEW = "harness.preview"
    HARNESS_APPLY = "harness.apply"
    HARNESS_ROLLBACK = "harness.rollback"
    PUBLICATION_PREVIEW = "publication.preview"
    PUBLICATION_PUBLISH = "publication.publish"


class BridgeEventName(StrEnum):
    DAEMON_STATE_CHANGED = "daemon.state_changed"
    COMPONENT_STATE_CHANGED = "component.state_changed"
    WORKSPACE_CHANGED = "workspace.changed"
    IDENTITY_CHANGED = "identity.changed"


@dataclass(frozen=True)
class CommandSpec:
    command: BridgeCommand
    request: type[LocalContractModel]
    response: type[LocalContractModel]
    capability: str | None
    mutating: bool = False
    cancellable: bool = False
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    max_request_bytes: int = DEFAULT_REQUEST_LIMIT_BYTES
    max_response_bytes: int = MAX_MESSAGE_BYTES


def _spec(
    command: BridgeCommand,
    request: type[LocalContractModel],
    response: type[LocalContractModel],
    capability: str | None,
    **options: Any,
) -> tuple[BridgeCommand, CommandSpec]:
    return command, CommandSpec(command, request, response, capability, **options)


BRIDGE_COMMANDS: dict[BridgeCommand, CommandSpec] = dict(
    (
        _spec(BridgeCommand.RUNTIME_HANDSHAKE, HandshakeRequest, HandshakeResponse, None),
        _spec(
            BridgeCommand.DAEMON_STATUS, DaemonControlRequest, DaemonControlResult, "daemon.control"
        ),
        _spec(
            BridgeCommand.DAEMON_ATTACH,
            DaemonControlRequest,
            DaemonControlResult,
            "daemon.control",
            mutating=True,
        ),
        _spec(
            BridgeCommand.DAEMON_START,
            DaemonControlRequest,
            DaemonControlResult,
            "daemon.control",
            mutating=True,
        ),
        _spec(
            BridgeCommand.DAEMON_STOP,
            DaemonControlRequest,
            DaemonControlResult,
            "daemon.control",
            mutating=True,
        ),
        _spec(
            BridgeCommand.DAEMON_RESTART,
            DaemonControlRequest,
            DaemonControlResult,
            "daemon.control",
            mutating=True,
        ),
        _spec(
            BridgeCommand.DAEMON_HEALTH,
            DaemonHealthRequest,
            DaemonHealth,
            "daemon.health",
        ),
        _spec(BridgeCommand.IDENTITY_GET_VIEW, EmptyPayload, IdentityView, "identity.view"),
        _spec(
            BridgeCommand.WORKSPACE_VALIDATE,
            WorkspaceValidateRequest,
            WorkspaceStatus,
            "workspace.config",
        ),
        _spec(
            BridgeCommand.WORKSPACE_GET_CONFIG,
            WorkspaceGetConfigRequest,
            LocalWorkspaceConfig,
            "workspace.config",
        ),
        _spec(
            BridgeCommand.WORKSPACE_CONFIRM_ROOTS,
            WorkspaceConfirmRootsRequest,
            WorkspaceConfirmRootsResult,
            "workspace.config",
        ),
        _spec(
            BridgeCommand.WORKSPACE_GIT_STATUS,
            WorkspaceScope,
            WorkspaceGitStatus,
            "workspace.config",
        ),
        _spec(
            BridgeCommand.WORKSPACE_SAVE_CONFIG,
            WorkspaceSaveConfigRequest,
            LocalWorkspaceConfig,
            "workspace.config",
            mutating=True,
        ),
        _spec(BridgeCommand.KNOWLEDGE_STATUS, WorkspaceScope, KnowledgeStatus, "knowledge.read"),
        _spec(
            BridgeCommand.KNOWLEDGE_SEARCH,
            KnowledgeSearchRequest,
            KnowledgeSearchResult,
            "knowledge.read",
            cancellable=True,
        ),
        _spec(
            BridgeCommand.KNOWLEDGE_GET_DOCUMENT,
            KnowledgeGetDocumentRequest,
            KnowledgeDocument,
            "knowledge.read",
        ),
        _spec(BridgeCommand.KNOWLEDGE_GRAPH_PAGE, GraphPageRequest, GraphPage, "knowledge.graph"),
        _spec(
            BridgeCommand.KNOWLEDGE_GRAPH_EXPAND, GraphExpandRequest, GraphPage, "knowledge.graph"
        ),
        _spec(
            BridgeCommand.KNOWLEDGE_REINDEX,
            KnowledgeReindexRequest,
            KnowledgeReindexResult,
            "knowledge.index",
            mutating=True,
            cancellable=True,
            timeout_ms=LONG_TIMEOUT_MS,
        ),
        _spec(BridgeCommand.CODE_GRAPH_STATUS, WorkspaceScope, CodeGraphStatus, "code_graph.read"),
        _spec(
            BridgeCommand.CODE_GRAPH_FIND_SYMBOLS,
            CodeSymbolQuery,
            CodeSymbolResult,
            "code_graph.read",
            cancellable=True,
        ),
        _spec(BridgeCommand.CODE_GRAPH_GRAPH_PAGE, GraphPageRequest, GraphPage, "code_graph.graph"),
        _spec(
            BridgeCommand.CODE_GRAPH_GRAPH_EXPAND, GraphExpandRequest, GraphPage, "code_graph.graph"
        ),
        _spec(
            BridgeCommand.CODE_GRAPH_REINDEX,
            CodeReindexRequest,
            CodeReindexResult,
            "code_graph.index",
            mutating=True,
            cancellable=True,
            timeout_ms=LONG_TIMEOUT_MS,
        ),
        _spec(BridgeCommand.HARNESS_DETECT, WorkspaceScope, HarnessDetectResult, "harness.read"),
        _spec(BridgeCommand.HARNESS_STATUS, HarnessStatusRequest, HarnessStatus, "harness.read"),
        _spec(BridgeCommand.HARNESS_PREVIEW, HarnessPreviewRequest, HarnessPlan, "harness.plan"),
        _spec(
            BridgeCommand.HARNESS_APPLY,
            HarnessApplyRequest,
            HarnessApplyResult,
            "harness.apply",
            mutating=True,
        ),
        _spec(
            BridgeCommand.HARNESS_ROLLBACK,
            HarnessRollbackRequest,
            HarnessRollbackResult,
            "harness.apply",
            mutating=True,
        ),
        _spec(
            BridgeCommand.PUBLICATION_PREVIEW,
            PublicationPreviewRequest,
            PublicationPlan,
            "publication.plan",
        ),
        _spec(
            BridgeCommand.PUBLICATION_PUBLISH,
            PublicationPublishRequest,
            PublicationResult,
            "publication.publish",
            mutating=True,
        ),
    )
)

DAEMON_COMMAND_ACTION: dict[BridgeCommand, DaemonAction] = {
    BridgeCommand.DAEMON_STATUS: DaemonAction.STATUS,
    BridgeCommand.DAEMON_ATTACH: DaemonAction.ATTACH,
    BridgeCommand.DAEMON_START: DaemonAction.START,
    BridgeCommand.DAEMON_STOP: DaemonAction.STOP,
    BridgeCommand.DAEMON_RESTART: DaemonAction.RESTART,
}


class ComponentStateChanged(LocalContractModel):
    component: ComponentId
    state: ComponentState
    workspace_id: UUID | None = None
    error: LocalError | None = None


BRIDGE_EVENTS: dict[BridgeEventName, type[LocalContractModel]] = {
    BridgeEventName.DAEMON_STATE_CHANGED: DaemonStatus,
    BridgeEventName.COMPONENT_STATE_CHANGED: ComponentStateChanged,
    BridgeEventName.WORKSPACE_CHANGED: WorkspaceStatus,
    BridgeEventName.IDENTITY_CHANGED: IdentityView,
}

JsonObject = dict[str, Any]


def _payload_bytes(payload: JsonObject) -> int:
    return len(json.dumps(payload, separators=(",", ":"), default=str).encode())


class _Envelope(LocalContractModel):
    protocol: Literal["studio.local/v1"] = "studio.local/v1"
    message_id: OpaqueId
    correlation_id: CorrelationId
    sent_at: UtcDatetime


class BridgeRequest(_Envelope):
    kind: Literal["request"] = "request"
    command: BridgeCommand
    payload: JsonObject = {}
    deadline_ms: int | None = Field(default=None, ge=100, le=LONG_TIMEOUT_MS)

    @model_validator(mode="after")
    def _payload_matches_spec(self) -> Self:
        spec = BRIDGE_COMMANDS[self.command]
        if _payload_bytes(self.payload) > spec.max_request_bytes:
            raise ValueError(f"request payload exceeds {spec.max_request_bytes} bytes")
        if self.deadline_ms is not None and self.deadline_ms > spec.timeout_ms:
            raise ValueError(f"deadline exceeds the {spec.timeout_ms} ms limit of this command")
        typed = spec.request.model_validate(self.payload)
        expected_action = DAEMON_COMMAND_ACTION.get(self.command)
        if expected_action is not None and getattr(typed, "action", None) != expected_action:
            raise ValueError(f"{self.command.value} requires action {expected_action.value}")
        return self

    def typed_payload(self) -> LocalContractModel:
        return BRIDGE_COMMANDS[self.command].request.model_validate(self.payload)


class BridgeResponse(_Envelope):
    kind: Literal["response"] = "response"
    request_id: OpaqueId
    command: BridgeCommand
    payload: JsonObject

    @model_validator(mode="after")
    def _payload_matches_spec(self) -> Self:
        spec = BRIDGE_COMMANDS[self.command]
        if _payload_bytes(self.payload) > spec.max_response_bytes:
            raise ValueError(f"response payload exceeds {spec.max_response_bytes} bytes")
        spec.response.model_validate(self.payload)
        return self

    def typed_payload(self) -> LocalContractModel:
        return BRIDGE_COMMANDS[self.command].response.model_validate(self.payload)


class BridgeErrorMessage(_Envelope):
    kind: Literal["error"] = "error"
    request_id: OpaqueId | None = None
    error: LocalError

    @model_validator(mode="after")
    def _error_correlates(self) -> Self:
        if self.error.correlation_id not in (None, self.correlation_id):
            raise ValueError("error correlation id differs from the envelope")
        return self


class BridgeEvent(_Envelope):
    kind: Literal["event"] = "event"
    event: BridgeEventName
    payload: JsonObject

    @model_validator(mode="after")
    def _payload_matches_event(self) -> Self:
        if _payload_bytes(self.payload) > DEFAULT_REQUEST_LIMIT_BYTES:
            raise ValueError("event payload too large")
        BRIDGE_EVENTS[self.event].model_validate(self.payload)
        return self


class BridgeProgress(_Envelope):
    kind: Literal["progress"] = "progress"
    request_id: OpaqueId
    phase: Identifier
    completed: int = Field(ge=0)
    total: int | None = Field(default=None, ge=0)
    message: ShortText | None = None

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        if self.total is not None and self.completed > self.total:
            raise ValueError("completed exceeds total")
        return self


class BridgeCancel(_Envelope):
    kind: Literal["cancel"] = "cancel"
    request_id: OpaqueId


BridgeMessage = Annotated[
    BridgeRequest
    | BridgeResponse
    | BridgeErrorMessage
    | BridgeEvent
    | BridgeProgress
    | BridgeCancel,
    Field(discriminator="kind"),
]
BRIDGE_MESSAGE_ADAPTER: TypeAdapter[BridgeMessage] = TypeAdapter(BridgeMessage)


def check_capability(command: BridgeCommand, granted: set[str]) -> LocalError | None:
    """Gate applied by the receiver before dispatch: a command whose capability
    was not negotiated is refused, never attempted."""
    spec = BRIDGE_COMMANDS[command]
    if spec.capability is None or spec.capability in granted:
        return None
    return LocalError(
        code=LocalErrorCode.CAPABILITY_MISSING,
        message="This command needs a capability that was not negotiated.",
        component=ComponentId.BRIDGE,
        retryable=False,
        details={"capability": spec.capability},
    )


def check_reply_correlation(request: BridgeRequest, reply: BridgeMessage) -> None:
    if isinstance(reply, BridgeRequest | BridgeCancel):
        raise ValueError("a request or a cancellation is not a reply")
    if isinstance(reply, BridgeResponse | BridgeProgress):
        if reply.request_id != request.message_id:
            raise ValueError("reply does not answer this request")
    if isinstance(reply, BridgeErrorMessage) and reply.request_id not in (None, request.message_id):
        raise ValueError("error does not answer this request")
    if reply.correlation_id != request.correlation_id:
        raise ValueError("reply carries another correlation id")


def allowlist_violations() -> list[str]:
    """Names in the command/event allowlist that look like a generic execution,
    filesystem, process or network primitive. Must always be empty."""
    names = [c.value for c in BridgeCommand] + [e.value for e in BridgeEventName]
    return [n for n in names if any(term in n for term in FORBIDDEN_PRIMITIVE_TERMS)]
