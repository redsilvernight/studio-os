from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError
from studio_contracts.builds import BuildStatus, ProducerJobKind, ProducerJobRequest
from studio_contracts.claims import ResourceClaimCreate, ResourceType
from studio_contracts.sessions import WorkSessionCreate
from studio_contracts.tasks import TaskCreate, TaskStatus, TaskUpdate

from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig, default_config_path
from studio_client.context import (
    ContextError,
    ContextPackage,
    ContextPackageComposer,
    ContextPackageOptions,
)
from studio_client.errors import StudioApiError
from studio_client.knowledge import GraphifyGraphProvider, ScopePolicy, VaultMemoryProvider
from studio_client.outbox import OutboxStore, connect, default_outbox_path
from studio_client.recording import (
    ActiveRecordingStore,
    OutboxRecordingStore,
    RecordingError,
    RecordingProvider,
)
from studio_client.tokens import KeyringTokenStore, MissingMachineToken, origin_of

_JSON_FLAG = "--json"


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(_JSON_FLAG, action="store_true", help="Print machine-readable JSON.")


def _idempotency_key() -> str:
    return str(uuid.uuid4())


def _parse_uuid(value: str, *, field: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        print(f"error: invalid {field}: {value!r} is not a UUID", file=sys.stderr)
        raise SystemExit(1) from None


def _load_config() -> ClientConfig:
    try:
        return ClientConfig()  # type: ignore[call-arg]  # fields resolved from STUDIO_CLIENT_* env/TOML
    except ValidationError as exc:
        missing = ", ".join(str(error["loc"][0]) for error in exc.errors() if error["loc"])
        print(
            f"error: missing configuration ({missing or exc.errors()[0]['msg']}): "
            f"set STUDIO_CLIENT_* environment variables or {default_config_path()}",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


def _print_model(model: BaseModel, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(model.model_dump(mode="json"), indent=2))
    else:
        print(model)


def _print_models(models: list[BaseModel], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps([m.model_dump(mode="json") for m in models], indent=2))
    elif not models:
        print("(none)")
    else:
        for model in models:
            print(model)


async def _with_client(
    config: ClientConfig, action: Callable[[StudioApiClient], Awaitable[Any]]
) -> Any:
    async with StudioApiClient(config, KeyringTokenStore()) as client:
        return await action(client)


def _run(config: ClientConfig, action: Callable[[StudioApiClient], Awaitable[Any]]) -> Any:
    """Every subcommand's single entry into async code — `StudioApiClient`
    is async-only, but the CLI itself is a synchronous argparse program."""
    try:
        return asyncio.run(_with_client(config, action))
    except MissingMachineToken as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except StudioApiError as exc:
        label = exc.error_code or exc.message
        print(f"error: {label} ({exc.status_code})", file=sys.stderr)
        raise SystemExit(1) from None


def login(argv: Sequence[str] | None = None) -> int:
    """Minimal enrollment gesture (sous-etape 6.1): paste the token printed
    by `studio-admin machine create` (or `POST /api/v1/machines`) once,
    store it in the OS keyring."""
    parser = argparse.ArgumentParser(
        prog="studio-client login",
        description="Store this machine's Studio OS token in the OS keyring.",
    )
    parser.add_argument(
        "--api-base-url",
        required=True,
        help="Studio OS API origin, e.g. https://vps.example.com",
    )
    args = parser.parse_args(argv)

    token = getpass.getpass("Machine token: ").strip()
    if not token:
        print("No token entered, aborting.", file=sys.stderr)
        return 1

    origin = origin_of(args.api_base_url)
    KeyringTokenStore().set_token(origin, token)
    print(f"Token stored for {origin}.")
    return 0


def _projects_list(args: argparse.Namespace, config: ClientConfig) -> None:
    projects = _run(config, lambda client: client.list_projects())
    _print_models(projects, as_json=args.json)


def _tasks_list(args: argparse.Namespace, config: ClientConfig) -> None:
    project_id = _parse_uuid(args.project_id, field="project_id") if args.project_id else None
    tasks = _run(
        config,
        lambda client: client.list_tasks(
            project_id=project_id, limit=args.limit, offset=args.offset
        ),
    )
    _print_models(tasks, as_json=args.json)


def _tasks_show(args: argparse.Namespace, config: ClientConfig) -> None:
    task_id = _parse_uuid(args.task_id, field="task_id")
    task = _run(config, lambda client: client.get_task(task_id))
    _print_model(task, as_json=args.json)


def _tasks_create(args: argparse.Namespace, config: ClientConfig) -> None:
    project_id = _parse_uuid(args.project_id, field="project_id")
    task_in = TaskCreate(project_id=project_id, title=args.title, description=args.description)
    key = _idempotency_key()
    task = _run(config, lambda client: client.create_task(task_in, idempotency_key=key))
    _print_model(task, as_json=args.json)


def _tasks_update(args: argparse.Namespace, config: ClientConfig) -> None:
    task_id = _parse_uuid(args.task_id, field="task_id")
    fields: dict[str, Any] = {}
    if args.title is not None:
        fields["title"] = args.title
    if args.description is not None:
        fields["description"] = args.description
    if args.status is not None:
        fields["status"] = TaskStatus(args.status)
    task_update = TaskUpdate(**fields)
    task = _run(
        config,
        lambda client: client.update_task(
            task_id, task_update, if_match_version=args.if_match_version
        ),
    )
    _print_model(task, as_json=args.json)


def _tasks_claim(args: argparse.Namespace, config: ClientConfig) -> None:
    task_id = _parse_uuid(args.task_id, field="task_id")
    task = _run(config, lambda client: client.claim_task(task_id))
    _print_model(task, as_json=args.json)


def _tasks_release(args: argparse.Namespace, config: ClientConfig) -> None:
    task_id = _parse_uuid(args.task_id, field="task_id")
    task = _run(config, lambda client: client.release_task(task_id))
    _print_model(task, as_json=args.json)


def _sessions_list(args: argparse.Namespace, config: ClientConfig) -> None:
    task_id = _parse_uuid(args.task_id, field="task_id") if args.task_id else None
    sessions = _run(config, lambda client: client.list_sessions(task_id=task_id))
    _print_models(sessions, as_json=args.json)


def _sessions_start(args: argparse.Namespace, config: ClientConfig) -> None:
    if config.machine_id is None:
        print(
            "No machine_id configured. Set STUDIO_CLIENT_MACHINE_ID or the "
            "config file's machine_id before starting a session.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    task_id = _parse_uuid(args.task_id, field="task_id")
    agent_id = _parse_uuid(args.agent_id, field="agent_id") if args.agent_id else None
    session_in = WorkSessionCreate(task_id=task_id, machine_id=config.machine_id, agent_id=agent_id)
    key = _idempotency_key()
    session = _run(config, lambda client: client.start_session(session_in, idempotency_key=key))
    _print_model(session, as_json=args.json)


def _sessions_end(args: argparse.Namespace, config: ClientConfig) -> None:
    session_id = _parse_uuid(args.session_id, field="session_id")
    session = _run(config, lambda client: client.end_session(session_id))
    _print_model(session, as_json=args.json)


def _claims_list(args: argparse.Namespace, config: ClientConfig) -> None:
    project_id = _parse_uuid(args.project_id, field="project_id") if args.project_id else None
    claims = _run(config, lambda client: client.list_claims(project_id=project_id))
    _print_models(claims, as_json=args.json)


def _claims_create(args: argparse.Namespace, config: ClientConfig) -> None:
    project_id = _parse_uuid(args.project_id, field="project_id")
    task_id = _parse_uuid(args.task_id, field="task_id") if args.task_id else None
    claim_in = ResourceClaimCreate(
        project_id=project_id,
        task_id=task_id,
        resource_path=args.resource_path,
        resource_type=ResourceType(args.resource_type),
        ttl_seconds=args.ttl_seconds,
    )
    key = _idempotency_key()
    claim = _run(config, lambda client: client.create_claim(claim_in, idempotency_key=key))
    _print_model(claim, as_json=args.json)


def _claims_renew(args: argparse.Namespace, config: ClientConfig) -> None:
    claim_id = _parse_uuid(args.claim_id, field="claim_id")
    claim = _run(config, lambda client: client.renew_claim(claim_id))
    _print_model(claim, as_json=args.json)


def _claims_release(args: argparse.Namespace, config: ClientConfig) -> None:
    claim_id = _parse_uuid(args.claim_id, field="claim_id")
    _run(config, lambda client: client.release_claim(claim_id))
    if args.json:
        print(json.dumps({"released": args.claim_id}))
    else:
        print(f"Released claim {args.claim_id}.")


def _ai_work_list(args: argparse.Namespace, config: ClientConfig) -> None:
    project_id = _parse_uuid(args.project_id, field="project_id") if args.project_id else None
    task_id = _parse_uuid(args.task_id, field="task_id") if args.task_id else None
    entries = _run(
        config, lambda client: client.list_ai_work(project_id=project_id, task_id=task_id)
    )
    _print_models(entries, as_json=args.json)


def _ai_work_show(args: argparse.Namespace, config: ClientConfig) -> None:
    """No `GET /ai-work/{id}` endpoint exists — filters the list client-side,
    consistent with the ledger's small expected size (same caveat as the
    review queue's own AI-work aggregation, DEC-0049)."""
    work_id = _parse_uuid(args.ai_work_id, field="ai_work_id")
    entries = _run(config, lambda client: client.list_ai_work())
    match = next((entry for entry in entries if entry.id == work_id), None)
    if match is None:
        print(f"error: ai_work {args.ai_work_id} not found", file=sys.stderr)
        raise SystemExit(1)
    _print_model(match, as_json=args.json)


def _review_queue_list(args: argparse.Namespace, config: ClientConfig) -> None:
    project_id = _parse_uuid(args.project_id, field="project_id") if args.project_id else None
    queue = _run(
        config,
        lambda client: client.get_review_queue(
            project_id=project_id, conflict_window_hours=args.conflict_window_hours
        ),
    )
    _print_models(queue.items, as_json=args.json)


def _recording_store() -> ActiveRecordingStore:
    """Local store resolving the machine's active recording. Tests override
    this factory so no real `%APPDATA%\\StudioOS\\outbox.sqlite3` is touched."""
    return OutboxRecordingStore(OutboxStore(connect(default_outbox_path())))


def _mark(args: argparse.Namespace, config: ClientConfig) -> None:
    """`studio mark "<label>"` (HUMAN/02-03): emit one
    `recording.marker.created` event, attached to the active recording when
    one is known and otherwise to the explicit `--project`/`--task`."""
    if config.machine_id is None:
        print(
            "No machine_id configured. Set STUDIO_CLIENT_MACHINE_ID or the "
            "config file's machine_id before creating a marker.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    machine_id = config.machine_id
    project_id = _parse_uuid(args.project, field="project_id") if args.project else None
    task_id = _parse_uuid(args.task, field="task_id") if args.task else None
    session_id = _parse_uuid(args.session, field="session_id") if args.session else None
    store = _recording_store()

    def action(client: StudioApiClient) -> Any:
        provider = RecordingProvider(
            client, actor_id=machine_id, machine_id=machine_id, store=store
        )
        return provider.mark(
            args.label,
            project_id=project_id,
            task_id=task_id,
            session_id=session_id,
            at=args.at,
        )

    try:
        marker = _run(config, action)
    except RecordingError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        raise SystemExit(1) from None
    if args.json:
        print(json.dumps(marker.event_payload(), indent=2))
    else:
        print(f"Marker {marker.marker_id} at {marker.timestamp.isoformat()}: {marker.label}")


def _notifications_list(args: argparse.Namespace, config: ClientConfig) -> None:
    """Alias of `review-queue list` (DEC-0051): notifications ARE the review
    queue, not a second, weaker mechanism — same client call, same output
    shape, just the human-facing name."""
    _review_queue_list(args, config)


def _timeline_list(args: argparse.Namespace, config: ClientConfig) -> None:
    project_id = _parse_uuid(args.project_id, field="project_id")
    since = datetime.fromisoformat(args.since) if args.since else None
    timeline = _run(
        config,
        lambda client: client.get_timeline(project_id, since=since, limit=args.limit),
    )
    if args.json:
        print(json.dumps(timeline.model_dump(mode="json"), indent=2))
    elif not timeline.days:
        print("(none)")
    else:
        for day in timeline.days:
            print(f"{day.date} ({len(day.events)} event(s))")
            for event in day.events:
                print(f"  {event.event_type}\t{event.server_timestamp}")


def _context_providers(
    config: ClientConfig,
) -> tuple[VaultMemoryProvider | None, GraphifyGraphProvider | None]:
    memory: VaultMemoryProvider | None = None
    if config.knowledge_vault_path is not None:
        memory = VaultMemoryProvider(
            vault_root=config.knowledge_vault_path,
            scope=ScopePolicy(allowed_prefixes=config.knowledge_scope_allow),
        )
    graph: GraphifyGraphProvider | None = None
    if config.knowledge_graph_dir is not None:
        graph = GraphifyGraphProvider(
            graph_dir=config.knowledge_graph_dir,
            source_root=config.knowledge_source_root,
        )
    return memory, graph


def _context_generate(args: argparse.Namespace, config: ClientConfig) -> None:
    project_id = _parse_uuid(args.project_id, field="project_id")
    task_id = _parse_uuid(args.task_id, field="task_id") if args.task_id else None
    memory_provider, graph_provider = _context_providers(config)
    options = ContextPackageOptions(
        include_memory=args.with_memory,
        include_graph=args.with_graph,
        include_git=args.with_git,
        include_library=args.with_library,
        memory_query=args.memory_query or "",
        graph_query=args.graph_query or "",
        budget_bytes=args.budget_bytes,
        events_limit=args.events_limit,
        decisions_limit=args.decisions_limit,
        ai_work_limit=args.ai_work_limit,
        memory_limit=args.memory_limit,
        graph_limit=args.graph_limit,
        git_commits_limit=args.git_commits_limit,
        library_limit=args.library_limit,
    )

    async def action(client: StudioApiClient) -> ContextPackage:
        composer = ContextPackageComposer(
            client,
            config,
            memory_provider=memory_provider,
            graph_provider=graph_provider,
        )
        return await composer.generate(project_id, task_id=task_id, options=options)

    try:
        package = _run(config, action)
    except ContextError as exc:
        print(f"error: {exc.message} ({exc.reason})", file=sys.stderr)
        raise SystemExit(1) from None

    if args.out:
        path = Path(args.out)
        path.write_text(package.to_json(indent=2), encoding="utf-8")
        if args.json:
            print(json.dumps({"written": str(path), "size_bytes": package.size_bytes()}))
        else:
            print(f"Context package written to {path} ({package.size_bytes()} bytes).")
        return

    if args.json:
        print(package.to_json(indent=2))
    else:
        print(f"Context package {package.manifest.package_id}")
        print(f"  size: {package.size_bytes()} bytes")
        print(f"  sources: {', '.join(s.kind for s in package.manifest.sources) or '(none)'}")
        if package.manifest.omitted:
            print("  omitted:")
            for omission in package.manifest.omitted:
                print(f"    - {omission.kind}: {omission.reason} ({omission.count})")


def _builds_list(args: argparse.Namespace, config: ClientConfig) -> None:
    project_id = _parse_uuid(args.project_id, field="project_id") if args.project_id else None
    try:
        status = BuildStatus(args.status) if args.status else None
    except ValueError:
        print(f"error: unknown build status {args.status!r}", file=sys.stderr)
        raise SystemExit(1) from None
    entries = _run(
        config,
        lambda client: client.list_builds(project_id=project_id, status=status),
    )
    _print_models(entries, as_json=args.json)


def _builds_show(args: argparse.Namespace, config: ClientConfig) -> None:
    build_id = _parse_uuid(args.build_id, field="build_id")
    try:
        build = _run(config, lambda client: client.get_build(build_id))
    except StudioApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    _print_model(build, as_json=args.json)


def _producer_run(args: argparse.Namespace, config: ClientConfig) -> None:
    project_id = _parse_uuid(args.project_id, field="project_id")
    task_id = _parse_uuid(args.task_id, field="task_id") if args.task_id else None
    job_in = ProducerJobRequest(
        project_id=project_id, kind=ProducerJobKind(args.kind), task_id=task_id
    )
    try:
        job = _run(
            config,
            lambda client: client.request_producer_job(job_in, idempotency_key=_idempotency_key()),
        )
    except StudioApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    _print_model(job, as_json=args.json)


def _adapters_list(args: argparse.Namespace, config: ClientConfig) -> None:
    """List the locally registered P10 adapters (open-string ids)."""
    from studio_client.adapters import get_adapter, list_adapters

    ids = list_adapters()
    if args.json:
        print(
            json.dumps([{"adapter_id": i, "managed_dir": get_adapter(i).managed_dir} for i in ids])
        )
    elif not ids:
        print("(none)")
    else:
        for adapter_id in ids:
            print(f"{adapter_id}\t{get_adapter(adapter_id).managed_dir}")


def _adapters_export(args: argparse.Namespace, config: ClientConfig) -> None:
    """Resolve one AgentDefinition over P7 HTTP, then project it locally
    with `studio_client.adapters` (P10/DEC-0074).

    Without `--out-dir` the artifacts print to stdout (dry-run); with it
    they materialize under the directory, confined to the adapter's
    managed dir. The adapter id is an open string — the dispatch stays
    in this local layer, never in the core."""
    from studio_client.adapters import AdapterError, get_adapter, materialize

    try:
        adapter = get_adapter(args.adapter)
    except AdapterError as exc:
        print(f"error: {exc.message} ({exc.code.value})", file=sys.stderr)
        raise SystemExit(1) from None

    project_id = _parse_uuid(args.project_id, field="project_id") if args.project_id else None
    if args.with_context and project_id is None:
        print("error: --with-context requires --project-id", file=sys.stderr)
        raise SystemExit(1)

    async def action(client: StudioApiClient) -> Any:
        resolved = await client.resolve_agent(args.stable_key, project_id=project_id)
        context = None
        if args.with_context:
            assert project_id is not None
            memory_provider, graph_provider = _context_providers(config)
            composer = ContextPackageComposer(
                client, config, memory_provider=memory_provider, graph_provider=graph_provider
            )
            context = await composer.generate(
                project_id,
                options=ContextPackageOptions(
                    include_library=True, library_limit=args.library_limit
                ),
            )
        return adapter.translate(resolved, context=context)

    try:
        result = _run(config, action)
    except AdapterError as exc:
        print(f"error: {exc.message} ({exc.code.value})", file=sys.stderr)
        raise SystemExit(1) from None

    if args.out_dir:
        try:
            written = materialize(
                result,
                Path(args.out_dir),
                overwrite=args.overwrite,
                managed_dir=adapter.managed_dir,
            )
        except AdapterError as exc:
            print(f"error: {exc.message} ({exc.code.value})", file=sys.stderr)
            raise SystemExit(1) from None
        if args.json:
            print(json.dumps({"written": [str(p) for p in written]}))
        else:
            for path in written:
                print(f"Wrote {path}.")
                for warning in result.warnings:
                    print(f"  warning {warning.code}: {warning.detail}")
        return

    if args.json:
        print(
            json.dumps(
                {
                    "adapter_id": result.adapter_id,
                    "artifacts": [{"path": a.path, "sha256": a.sha256} for a in result.artifacts],
                    "warnings": [{"code": w.code, "detail": w.detail} for w in result.warnings],
                },
                indent=2,
            )
        )
        return
    for artifact in result.artifacts:
        print(f"--- {artifact.path} ---")
        print(artifact.content)
    for warning in result.warnings:
        print(f"warning {warning.code}: {warning.detail}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="studio-client")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "login",
        help="Store the machine token in the OS keyring (see `studio-client login --help`).",
    )

    projects_parser = subparsers.add_parser("projects", help="Projects.")
    projects_sub = projects_parser.add_subparsers(dest="projects_command", required=True)
    projects_list = projects_sub.add_parser("list", help="List projects.")
    _add_json_flag(projects_list)
    projects_list.set_defaults(func=_projects_list)

    tasks_parser = subparsers.add_parser("tasks", help="Tasks.")
    tasks_sub = tasks_parser.add_subparsers(dest="tasks_command", required=True)

    tasks_list = tasks_sub.add_parser("list", help="List tasks.")
    tasks_list.add_argument("--project-id")
    tasks_list.add_argument("--limit", type=int, default=100)
    tasks_list.add_argument("--offset", type=int, default=0)
    _add_json_flag(tasks_list)
    tasks_list.set_defaults(func=_tasks_list)

    tasks_show = tasks_sub.add_parser("show", help="Show a task.")
    tasks_show.add_argument("task_id")
    _add_json_flag(tasks_show)
    tasks_show.set_defaults(func=_tasks_show)

    tasks_create = tasks_sub.add_parser("create", help="Create a task.")
    tasks_create.add_argument("--project-id", required=True)
    tasks_create.add_argument("--title", required=True)
    tasks_create.add_argument("--description")
    _add_json_flag(tasks_create)
    tasks_create.set_defaults(func=_tasks_create)

    tasks_update = tasks_sub.add_parser("update", help="Update a task.")
    tasks_update.add_argument("task_id")
    tasks_update.add_argument("--if-match-version", type=int, required=True)
    tasks_update.add_argument("--title")
    tasks_update.add_argument("--description")
    tasks_update.add_argument("--status", choices=[status.value for status in TaskStatus])
    _add_json_flag(tasks_update)
    tasks_update.set_defaults(func=_tasks_update)

    tasks_claim = tasks_sub.add_parser("claim", help="Claim a task for this machine.")
    tasks_claim.add_argument("task_id")
    _add_json_flag(tasks_claim)
    tasks_claim.set_defaults(func=_tasks_claim)

    tasks_release = tasks_sub.add_parser("release", help="Release a claimed task.")
    tasks_release.add_argument("task_id")
    _add_json_flag(tasks_release)
    tasks_release.set_defaults(func=_tasks_release)

    sessions_parser = subparsers.add_parser("sessions", help="Work sessions.")
    sessions_sub = sessions_parser.add_subparsers(dest="sessions_command", required=True)

    sessions_list = sessions_sub.add_parser("list", help="List sessions.")
    sessions_list.add_argument("--task-id")
    _add_json_flag(sessions_list)
    sessions_list.set_defaults(func=_sessions_list)

    sessions_start = sessions_sub.add_parser("start", help="Start a work session.")
    sessions_start.add_argument("--task-id", required=True)
    sessions_start.add_argument("--agent-id")
    _add_json_flag(sessions_start)
    sessions_start.set_defaults(func=_sessions_start)

    sessions_end = sessions_sub.add_parser("end", help="End a work session.")
    sessions_end.add_argument("session_id")
    _add_json_flag(sessions_end)
    sessions_end.set_defaults(func=_sessions_end)

    claims_parser = subparsers.add_parser("claims", help="Resource claims (soft locks).")
    claims_sub = claims_parser.add_subparsers(dest="claims_command", required=True)

    claims_list = claims_sub.add_parser("list", help="List claims.")
    claims_list.add_argument("--project-id")
    _add_json_flag(claims_list)
    claims_list.set_defaults(func=_claims_list)

    claims_create = claims_sub.add_parser("create", help="Create a resource claim.")
    claims_create.add_argument("--project-id", required=True)
    claims_create.add_argument("--task-id")
    claims_create.add_argument("--resource-path", required=True)
    claims_create.add_argument("--resource-type", choices=["file", "folder"], required=True)
    claims_create.add_argument("--ttl-seconds", type=int, required=True)
    _add_json_flag(claims_create)
    claims_create.set_defaults(func=_claims_create)

    claims_renew = claims_sub.add_parser("renew", help="Renew a claim's TTL.")
    claims_renew.add_argument("claim_id")
    _add_json_flag(claims_renew)
    claims_renew.set_defaults(func=_claims_renew)

    claims_release = claims_sub.add_parser("release", help="Release a claim.")
    claims_release.add_argument("claim_id")
    _add_json_flag(claims_release)
    claims_release.set_defaults(func=_claims_release)

    ai_work_parser = subparsers.add_parser("ai-work", help="AI work ledger.")
    ai_work_sub = ai_work_parser.add_subparsers(dest="ai_work_command", required=True)

    ai_work_list = ai_work_sub.add_parser("list", help="List AI work ledger entries.")
    ai_work_list.add_argument("--project-id")
    ai_work_list.add_argument("--task-id")
    _add_json_flag(ai_work_list)
    ai_work_list.set_defaults(func=_ai_work_list)

    ai_work_show = ai_work_sub.add_parser("show", help="Show one AI work ledger entry.")
    ai_work_show.add_argument("ai_work_id")
    _add_json_flag(ai_work_show)
    ai_work_show.set_defaults(func=_ai_work_show)

    review_queue_parser = subparsers.add_parser(
        "review-queue", help="Items awaiting a human decision."
    )
    review_queue_sub = review_queue_parser.add_subparsers(
        dest="review_queue_command", required=True
    )

    review_queue_list = review_queue_sub.add_parser("list", help="List review queue items.")
    review_queue_list.add_argument("--project-id")
    review_queue_list.add_argument("--conflict-window-hours", type=int, default=None)
    _add_json_flag(review_queue_list)
    review_queue_list.set_defaults(func=_review_queue_list)

    notifications_parser = subparsers.add_parser(
        "notifications", help="Alias of review-queue (DEC-0051)."
    )
    notifications_sub = notifications_parser.add_subparsers(
        dest="notifications_command", required=True
    )

    notifications_list = notifications_sub.add_parser("list", help="List notifications.")
    notifications_list.add_argument("--project-id")
    notifications_list.add_argument("--conflict-window-hours", type=int, default=None)
    _add_json_flag(notifications_list)
    notifications_list.set_defaults(func=_notifications_list)

    timeline_parser = subparsers.add_parser("timeline", help="Day-grouped project activity.")
    timeline_sub = timeline_parser.add_subparsers(dest="timeline_command", required=True)

    timeline_list = timeline_sub.add_parser("list", help="List the timeline.")
    timeline_list.add_argument("--project-id", required=True)
    timeline_list.add_argument("--since")
    timeline_list.add_argument("--limit", type=int, default=200)
    _add_json_flag(timeline_list)
    timeline_list.set_defaults(func=_timeline_list)

    mark_parser = subparsers.add_parser(
        "mark",
        help="Mark a moment in the active recording.",
    )
    mark_parser.add_argument("label", help="Short human label for the moment.")
    mark_parser.add_argument("--project", help="Project UUID (default: active recording).")
    mark_parser.add_argument("--task", help="Task UUID to attach the marker to.")
    mark_parser.add_argument("--session", help="Work session UUID to attach the marker to.")
    mark_parser.add_argument(
        "--at",
        help="ISO-8601 timestamp, or a signed offset (+90, -45s) relative to the "
        "recording start when a recording is active, otherwise to now.",
    )
    _add_json_flag(mark_parser)
    mark_parser.set_defaults(func=_mark)

    context_parser = subparsers.add_parser(
        "context", help="Compose a local Context Package (DEC-0057)."
    )
    context_sub = context_parser.add_subparsers(dest="context_command", required=True)

    context_generate = context_sub.add_parser("generate", help="Generate a context package.")
    context_generate.add_argument("--project-id", required=True, help="Project UUID.")
    context_generate.add_argument("--task-id", help="Optional task UUID.")
    context_generate.add_argument(
        "--with-memory", action="store_true", help="Include exposed vault notes (opt-in)."
    )
    context_generate.add_argument(
        "--with-graph", action="store_true", help="Include Graphify relevant files (opt-in)."
    )
    context_generate.add_argument(
        "--with-git", action="store_true", help="Include bounded Git snapshot (opt-in)."
    )
    context_generate.add_argument(
        "--with-library",
        action="store_true",
        help="Include AI Library rule/skill excerpts via StudioApiClient (P7 HTTP, opt-in).",
    )
    context_generate.add_argument("--memory-query", help="Search query for vault notes.")
    context_generate.add_argument("--graph-query", help="Topic/path for Graphify lookup.")
    context_generate.add_argument(
        "--budget-bytes", type=int, default=256 * 1024, help="Hard serialized budget."
    )
    context_generate.add_argument("--events-limit", type=int, default=50)
    context_generate.add_argument("--decisions-limit", type=int, default=20)
    context_generate.add_argument("--ai-work-limit", type=int, default=20)
    context_generate.add_argument("--memory-limit", type=int, default=5)
    context_generate.add_argument("--graph-limit", type=int, default=10)
    context_generate.add_argument("--git-commits-limit", type=int, default=10)
    context_generate.add_argument("--library-limit", type=int, default=100)
    context_generate.add_argument(
        "--out", help="Write the package to this file instead of printing a summary."
    )
    _add_json_flag(context_generate)
    context_generate.set_defaults(func=_context_generate)

    builds_parser = subparsers.add_parser("builds", help="CI builds (etape 9.1).")
    builds_sub = builds_parser.add_subparsers(dest="builds_command", required=True)

    builds_list = builds_sub.add_parser("list", help="List builds, newest first.")
    builds_list.add_argument("--project-id")
    builds_list.add_argument("--status")
    _add_json_flag(builds_list)
    builds_list.set_defaults(func=_builds_list)

    builds_show = builds_sub.add_parser("show", help="Show one build.")
    builds_show.add_argument("build_id")
    _add_json_flag(builds_show)
    builds_show.set_defaults(func=_builds_show)

    producer_parser = subparsers.add_parser("producer", help="Studio Producer (etape 9.1).")
    producer_sub = producer_parser.add_subparsers(dest="producer_command", required=True)

    producer_run = producer_sub.add_parser("run", help="Run a Producer analysis.")
    producer_run.add_argument("--project-id", required=True)
    producer_run.add_argument(
        "--kind",
        required=True,
        choices=["priority_analysis", "blocker_detection", "parallelization", "decomposition"],
    )
    producer_run.add_argument("--task-id", help="Required for decomposition.")
    _add_json_flag(producer_run)
    producer_run.set_defaults(func=_producer_run)

    adapters_parser = subparsers.add_parser(
        "adapters", help="Project a resolved agent to a local harness (P10)."
    )
    adapters_sub = adapters_parser.add_subparsers(dest="adapters_command", required=True)

    adapters_list = adapters_sub.add_parser("list", help="List local adapters.")
    _add_json_flag(adapters_list)
    adapters_list.set_defaults(func=_adapters_list)

    adapters_export = adapters_sub.add_parser(
        "export", help="Resolve an agent (P7 HTTP) and translate it locally."
    )
    adapters_export.add_argument(
        "--adapter", required=True, help="Open adapter id, e.g. claude-code, opencode."
    )
    adapters_export.add_argument("--stable-key", required=True, help="AgentDefinition stable key.")
    adapters_export.add_argument("--project-id", help="Project UUID for resolution context.")
    adapters_export.add_argument(
        "--out-dir", help="Materialize under this directory (default: print to stdout)."
    )
    adapters_export.add_argument(
        "--overwrite", action="store_true", help="Replace existing managed files."
    )
    adapters_export.add_argument(
        "--with-context",
        action="store_true",
        help="Attach a generic P9 Context Package (requires --project-id).",
    )
    adapters_export.add_argument("--library-limit", type=int, default=100)
    _add_json_flag(adapters_export)
    adapters_export.set_defaults(func=_adapters_export)

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv[:1] == ["login"]:
        raise SystemExit(login(argv[1:]))

    parser = _build_parser()
    args = parser.parse_args(argv)
    config = _load_config()
    args.func(args, config)


if __name__ == "__main__":
    main()
