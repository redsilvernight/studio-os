from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError
from studio_contracts.claims import ResourceClaimCreate, ResourceType
from studio_contracts.sessions import WorkSessionCreate
from studio_contracts.tasks import TaskCreate, TaskStatus, TaskUpdate

from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig, default_config_path
from studio_client.errors import StudioApiError
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
