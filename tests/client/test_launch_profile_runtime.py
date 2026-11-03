"""Bloc B (DEC-0198): the daemon applies the work profile a real launch
carries. The pin recorded at creation is recomputed through the common
resolver when the run starts, the local policy still decides, and a profiled
launch never falls back to the legacy coding mode."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from studio_client.config import ClientConfig
from studio_client.daemon.launch_executor import LaunchExecutor
from studio_client.daemon.launch_prepare import LaunchPreparer
from studio_client.daemon.launch_report import LaunchReporter
from studio_client.daemon.launch_runner import LaunchRunner
from studio_client.daemon.runtime import build_launch_resolver, resolve_launch_profile
from studio_client.harness.base import AccessMode, Detection, DetectionState
from studio_client.harness.registry import HarnessRegistry
from studio_client.outbox import OutboxStore
from studio_client.outbox.models import OutboxTable
from studio_client.outbox.store import connect
from studio_contracts.execution_snapshot import ExecutionSnapshotPayload
from studio_contracts.library import LibraryKind, LibraryScope, VersionOrigin
from studio_contracts.profiles import (
    LaunchProfilePin,
    MachinePolicy,
    ProfilePermission,
    pin_profile,
    profile_elements,
    reference_work_profile,
)
from studio_contracts.resolution import (
    Provenance,
    ProvenanceSource,
    ResolvedAgent,
    ResolvedAgentDefinition,
    ResolvedRule,
)
from studio_contracts.task_launch import TaskLaunch

from tests.client.test_launch_executor import FakeAdapter, FakeClient, _launch, _repo

AGENT_KEY = "architect"
AGENT_ID = uuid4()
RULE_ID = uuid4()
READ_ONLY_PROFILE = "architecture-read-only"
CODING_PROFILE = "coding"


def _definition(version: int = 1) -> ResolvedAgentDefinition:
    return ResolvedAgentDefinition(
        agent=ResolvedAgent(
            resource_id=AGENT_ID,
            kind=LibraryKind.AGENT_DEFINITION,
            stable_key=AGENT_KEY,
            scope=LibraryScope.STUDIO,
            version=version,
            version_origin=VersionOrigin.ACTIVE,
            content={"prompt": "Never reveal the plan."},
            provenance=Provenance(source=ProvenanceSource.ACTIVE_POINTER),
        ),
        rules=[
            ResolvedRule(
                resource_id=RULE_ID,
                stable_key="no-force-push",
                scope=LibraryScope.PROJECT,
                version=2,
                version_origin=VersionOrigin.LOCK,
                content={"body": "Never force-push."},
            )
        ],
    )


def _pin(reference: str, *, version: int = 1) -> LaunchProfilePin:
    """The pin the server computed at creation, against Library version
    `version`."""
    return pin_profile(
        reference_work_profile(reference, AGENT_KEY),
        profile_elements(_definition(version)),
    )


def _profiled(reference: str, *, version: int = 1) -> TaskLaunch:
    return _launch().model_copy(
        update={"agent_stable_key": AGENT_KEY, "profile": _pin(reference, version=version)}
    )


async def test_v2_daemon_recomputes_a_legacy_v1_pin() -> None:
    definition = _definition()
    work = reference_work_profile(READ_ONLY_PROFILE, AGENT_KEY, contract_version=1)
    pin = pin_profile(work, profile_elements(definition))
    launch = _launch().model_copy(update={"agent_stable_key": AGENT_KEY, "profile": pin})
    resolved = await resolve_launch_profile(ResolvingClient(definition), launch)
    assert resolved is not None
    assert resolved.resolved == pin


class ResolvingClient(FakeClient):
    def __init__(self, definition: ResolvedAgentDefinition | None, *, fail: bool = False) -> None:
        super().__init__()
        self.definition = definition
        self.fail = fail
        self.calls: list[str] = []

    async def resolve_agent(
        self, stable_key: str, *, project_id: UUID | None = None
    ) -> ResolvedAgentDefinition:
        self.calls.append(stable_key)
        if self.fail or self.definition is None:
            raise RuntimeError("resolver unreachable")
        return self.definition


class ReadOnlyFake(FakeAdapter):
    access_modes = frozenset({AccessMode.READ_ONLY, AccessMode.WORKSPACE_WRITE})

    def __init__(self, argv: tuple[str, ...]) -> None:
        super().__init__(argv)
        self.modes: list[AccessMode] = []

    def headless_argv(
        self, prompt: str, *, mode: AccessMode = AccessMode.WORKSPACE_WRITE
    ) -> tuple[str, ...]:
        self.require_mode(mode)
        self.modes.append(mode)
        return self._argv

    def detect(self, ctx: Any) -> Detection:
        return Detection(state=DetectionState.CONFIGURED, version="1.2.3")


def _machine(
    tmp_path: Path,
    client: ResolvingClient,
    adapter: ReadOnlyFake,
    *,
    permissions: list[ProfilePermission] | None,
    opt_in: bool = True,
) -> tuple[LaunchExecutor, OutboxStore]:
    repo = _repo(tmp_path)
    store = OutboxStore(connect(tmp_path / "outbox.sqlite3"))
    policy = MachinePolicy(
        opt_in=opt_in,
        max_concurrent=1,
        allowed_harnesses=["fake"],
        permissions=permissions,
    )
    executor = LaunchExecutor(
        client=client,  # type: ignore[arg-type]
        reporter=LaunchReporter(store),
        preparer=LaunchPreparer(fetch=False),
        runner=LaunchRunner(),
        resolve=build_launch_resolver(
            client,  # type: ignore[arg-type]
            HarnessRegistry([adapter]),
            ClientConfig(api_base_url="https://studio.example"),
            workspace_repo=lambda _pid: repo,
        ),
        machine_policy=lambda: policy,
        capture_snapshots=True,
    )
    return executor, store


async def _run(executor: LaunchExecutor, launch: TaskLaunch) -> None:
    executor.submit(launch)
    await executor._tasks[launch.id]


def _rows(store: OutboxStore) -> list[dict[str, Any]]:
    return [row.payload for row in store.list_pending(OutboxTable.MUTATIONS)]


def _statuses(store: OutboxStore) -> list[str]:
    return [str(row["status"]) for row in _status_rows(store)]


def _status_rows(store: OutboxStore) -> list[dict[str, Any]]:
    return [row for row in _rows(store) if "status" in row]


def _excerpt(store: OutboxStore) -> str:
    return " ".join(str(row.get("output_excerpt") or "") for row in _rows(store))


def _snapshot(store: OutboxStore) -> ExecutionSnapshotPayload:
    rows = [
        row
        for row in store.list_pending(OutboxTable.MUTATIONS)
        if str(row.extra.get("path")).endswith("/snapshot")
    ]
    assert len(rows) == 1
    return ExecutionSnapshotPayload.model_validate(rows[0].payload)


def _marker(tmp_path: Path) -> tuple[Path, tuple[str, ...]]:
    marker = tmp_path / "ran.txt"
    return marker, ("-c", f"open({str(marker)!r}, 'w').write('x')")


OK_SCRIPT = ("-c", "print('studio_start_work then studio_handoff')")


# --- criterion 1: the profile the launch carries is the mode that runs --------


async def test_read_only_profile_runs_in_read_only_mode(tmp_path: Path) -> None:
    adapter = ReadOnlyFake(OK_SCRIPT)
    executor, store = _machine(
        tmp_path, ResolvingClient(_definition()), adapter, permissions=["read"]
    )
    await _run(executor, _profiled(READ_ONLY_PROFILE))

    assert _statuses(store) == ["preparing", "running", "succeeded"]
    assert adapter.modes == [AccessMode.READ_ONLY]


async def test_coding_profile_is_refused_on_a_read_only_machine(tmp_path: Path) -> None:
    marker, argv = _marker(tmp_path)
    executor, store = _machine(
        tmp_path, ResolvingClient(_definition()), ReadOnlyFake(argv), permissions=["read"]
    )
    await _run(executor, _profiled(CODING_PROFILE))

    assert _statuses(store) == ["failed"]
    assert _status_rows(store)[0]["reason_code"] == "preparation_failed"
    assert "reason=permission_denied" in _excerpt(store)
    assert not marker.exists()


async def test_coding_profile_runs_when_the_machine_grants_writing(tmp_path: Path) -> None:
    adapter = ReadOnlyFake(OK_SCRIPT)
    executor, store = _machine(
        tmp_path,
        ResolvingClient(_definition()),
        adapter,
        permissions=["read", "write", "execute", "launch"],
    )
    await _run(executor, _profiled(CODING_PROFILE))

    assert _statuses(store) == ["preparing", "running", "succeeded"]
    assert adapter.modes == [AccessMode.WORKSPACE_WRITE]


# --- criterion 2: the Library changed between creation and start ---------------


async def test_library_change_since_creation_refuses_with_profile_version_changed(
    tmp_path: Path,
) -> None:
    marker, argv = _marker(tmp_path)
    client = ResolvingClient(_definition(version=2))
    executor, store = _machine(tmp_path, client, ReadOnlyFake(argv), permissions=["read"])

    await _run(executor, _profiled(READ_ONLY_PROFILE, version=1))

    assert _statuses(store) == ["failed"]
    assert "reason=profile_version_changed" in _excerpt(store)
    assert not marker.exists()


async def test_snapshot_reports_the_previewed_and_the_applied_profile(tmp_path: Path) -> None:
    executor, store = _machine(
        tmp_path, ResolvingClient(_definition()), ReadOnlyFake(OK_SCRIPT), permissions=["read"]
    )
    launch = _profiled(READ_ONLY_PROFILE)
    await _run(executor, launch)

    payload = _snapshot(store)
    pin = _pin(READ_ONLY_PROFILE)
    assert payload.resolution is not None and payload.resolution.profile is not None
    assert payload.resolution.profile.digest == pin.digest
    assert payload.applied is not None and payload.applied.profile is not None
    assert payload.applied.profile.stable_key == READ_ONLY_PROFILE
    assert payload.applied.profile.digest == pin.digest
    assert payload.applied.access_mode == AccessMode.READ_ONLY.value
    assert payload.profile_drift is False


async def test_snapshot_shows_the_drift_when_the_library_moved(tmp_path: Path) -> None:
    executor, store = _machine(
        tmp_path,
        ResolvingClient(_definition(version=2)),
        ReadOnlyFake(OK_SCRIPT),
        permissions=["read"],
    )
    await _run(executor, _profiled(READ_ONLY_PROFILE, version=1))

    payload = _snapshot(store)
    assert payload.profile_drift is True
    assert payload.resolution is not None and payload.resolution.profile is not None
    assert payload.applied is not None and payload.applied.profile is not None
    assert payload.resolution.profile.digest == _pin(READ_ONLY_PROFILE, version=1).digest
    assert payload.applied.profile.digest == _pin(READ_ONLY_PROFILE, version=2).digest
    assert payload.applied.access_mode is None
    assert "running" not in _statuses(store)


# --- criterion 3: an unprofiled launch is untouched, a profiled one fails closed


async def test_launch_without_profile_keeps_the_legacy_coding_mode(tmp_path: Path) -> None:
    adapter = ReadOnlyFake(OK_SCRIPT)
    executor, store = _machine(
        tmp_path, ResolvingClient(_definition()), adapter, permissions=["read"]
    )
    await _run(executor, _launch())

    assert _statuses(store) == ["preparing", "running", "succeeded"]
    assert adapter.modes == [AccessMode.WORKSPACE_WRITE]
    assert _snapshot(store).resolution is None


async def test_unreachable_resolver_refuses_instead_of_running_legacy(tmp_path: Path) -> None:
    marker, argv = _marker(tmp_path)
    executor, store = _machine(
        tmp_path, ResolvingClient(None, fail=True), ReadOnlyFake(argv), permissions=["read"]
    )
    await _run(executor, _profiled(READ_ONLY_PROFILE))

    assert _statuses(store) == ["failed"]
    assert "running" not in _statuses(store)
    assert not marker.exists()


async def test_unknown_profile_key_refuses_closed(tmp_path: Path) -> None:
    marker, argv = _marker(tmp_path)
    executor, store = _machine(
        tmp_path, ResolvingClient(_definition()), ReadOnlyFake(argv), permissions=["read"]
    )
    launch = _launch().model_copy(
        update={
            "agent_stable_key": AGENT_KEY,
            "profile": _pin(CODING_PROFILE).model_copy(update={"stable_key": "not-a-profile"}),
        }
    )
    await _run(executor, launch)

    assert _statuses(store) == ["failed"]
    assert not marker.exists()


async def test_profiled_launch_without_agent_definition_refuses_closed(tmp_path: Path) -> None:
    marker, argv = _marker(tmp_path)
    executor, store = _machine(
        tmp_path, ResolvingClient(_definition()), ReadOnlyFake(argv), permissions=["read"]
    )
    await _run(executor, _launch().model_copy(update={"profile": _pin(READ_ONLY_PROFILE)}))

    assert _statuses(store) == ["failed"]
    assert "running" not in _statuses(store)
    assert not marker.exists()


async def test_machine_opt_out_still_refuses_a_read_only_profile(tmp_path: Path) -> None:
    marker, argv = _marker(tmp_path)
    executor, store = _machine(
        tmp_path,
        ResolvingClient(_definition()),
        ReadOnlyFake(argv),
        permissions=["read"],
        opt_in=False,
    )
    await _run(executor, _profiled(READ_ONLY_PROFILE))

    assert _statuses(store) == ["failed"]
    assert "reason=machine_opt_in_off" in _excerpt(store)
    assert not marker.exists()


# --- resolver: the pin is recomputed, not trusted --------------------------------


async def test_resolver_without_a_profile_returns_none(tmp_path: Path) -> None:
    client = ResolvingClient(_definition())
    resolver = build_launch_resolver(
        client,  # type: ignore[arg-type]
        HarnessRegistry([ReadOnlyFake(OK_SCRIPT)]),
        ClientConfig(api_base_url="https://studio.example"),
        workspace_repo=lambda _pid: tmp_path,
    )
    resolved = await resolver(_launch())
    assert resolved is not None
    assert resolved.profile is None
    assert client.calls == []


async def test_resolver_recomputes_the_pin_through_the_common_resolver(tmp_path: Path) -> None:
    client = ResolvingClient(_definition())
    resolver = build_launch_resolver(
        client,  # type: ignore[arg-type]
        HarnessRegistry([ReadOnlyFake(OK_SCRIPT)]),
        ClientConfig(api_base_url="https://studio.example"),
        workspace_repo=lambda _pid: tmp_path,
    )
    launch = _profiled(READ_ONLY_PROFILE)
    resolved = await resolver(launch)

    assert resolved is not None and resolved.profile is not None
    assert client.calls == [AGENT_KEY]
    assert resolved.profile.expected == launch.profile
    assert resolved.profile.resolved == _pin(READ_ONLY_PROFILE)
    assert resolved.profile.permissions == ("read",)


async def test_resolver_pin_never_matches_when_the_library_moved(tmp_path: Path) -> None:
    client = ResolvingClient(_definition(version=2))
    launch = _profiled(READ_ONLY_PROFILE, version=1)

    profile = await resolve_launch_profile(client, launch)  # type: ignore[arg-type]

    assert profile is not None
    assert profile.expected != profile.resolved
    assert profile.resolved.digest == _pin(READ_ONLY_PROFILE, version=2).digest
