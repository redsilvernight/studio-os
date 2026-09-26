"""Server-side provisioning CLI (DEC-0011). Run on the VPS, never exposed over
HTTP: bootstrapping the first admin user has no machine token to authenticate
against, and SSH access to the VPS is already the trust root for this stack's
other secrets (see docker/docker-compose.yml)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role

from studio_api.db.models.project import ProjectModel
from studio_api.db.models.user import UserModel
from studio_api.db.session import get_session_factory
from studio_api.services import github as github_service
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service
from studio_api.services import transfers as transfers_service
from studio_api.settings import get_settings
from studio_api.storage.provider import get_storage


async def _bootstrap_admin(display_name: str, email: str, password: str | None) -> None:
    async with get_session_factory()() as session:
        user = await provisioning_service.bootstrap_admin(session, display_name, email)
        if password:
            await provisioning_service.set_user_password(session, email, password)
        print(f"admin user created: {user.id} ({user.email})")


async def _create_user(display_name: str, email: str, role: str) -> None:
    normalized_email = email.strip().lower()
    async with get_session_factory()() as session:
        user = await provisioning_service.create_user(
            session, display_name.strip(), normalized_email, role
        )
        print(f"user created: {user.id} ({user.email}, {user.role})")


def _read_secret_from_stdin(what: str) -> str:
    value = sys.stdin.readline()
    if not value:
        print(f"error: no {what} received on stdin", file=sys.stderr)
        raise SystemExit(1)
    return value.rstrip("\r\n")


def _read_password_from_stdin() -> str:
    return _read_secret_from_stdin("password")


async def _set_password(email: str, password: str) -> None:
    async with get_session_factory()() as session:
        await provisioning_service.set_user_password(session, email, password)
        print(f"password set for {email}")


async def _update_user_state(action: str, email: str) -> None:
    operations = {
        "disable": provisioning_service.disable_user,
        "enable": provisioning_service.enable_user,
        "revoke-sessions": provisioning_service.revoke_user_sessions,
    }
    async with get_session_factory()() as session:
        user = await operations[action](session, email.strip().lower())
        state = "disabled" if user.disabled_at is not None else "enabled"
        print(f"{action}: {user.email} ({state}, auth_version={user.auth_version})")


async def _create_machine(owner_email: str, display_name: str) -> None:
    async with get_session_factory()() as session:
        owner = await provisioning_service.get_user_by_email(session, owner_email)
        if owner is None:
            print(f"no user with email {owner_email}", file=sys.stderr)
            raise SystemExit(1)
        machine, token = await provisioning_service.create_machine(session, owner.id, display_name)
        print(f"machine created: {machine.id}")
        print(f"token (store now, never shown again): {token}")


async def _revoke_machine(machine_id: str) -> None:
    async with get_session_factory()() as session:
        machine = await provisioning_service.get_machine(session, UUID(machine_id))
        if machine is None:
            print(f"no machine {machine_id}", file=sys.stderr)
            raise SystemExit(1)
        await provisioning_service.revoke_machine(session, machine)
        print(f"machine revoked: {machine_id}")


async def _list_machines(owner_email: str | None) -> None:
    async with get_session_factory()() as session:
        rows = await provisioning_service.list_machines(session, owner_email)
    if not rows:
        print("no machine found")
        return
    print(f"{'machine_id':<36}  {'display_name':<20} {'owner':<24} status")
    for machine, owner in rows:
        status_label = "active" if machine.credential_revoked_at is None else "revoked"
        print(f"{str(machine.id):<36}  {machine.display_name:<20} {owner.email:<24} {status_label}")


async def _show_machine_by_token(token: str) -> None:
    async with get_session_factory()() as session:
        row = await provisioning_service.get_machine_by_token(session, token)
    if row is None:
        print("no machine matches this token", file=sys.stderr)
        raise SystemExit(1)
    machine, owner = row
    status_label = "active" if machine.credential_revoked_at is None else "revoked"
    print(f"machine_id: {machine.id}")
    print(f"display_name: {machine.display_name}")
    print(f"owner_email: {owner.email}")
    print(f"status: {status_label}")


async def _create_project(slug: str, name: str, description: str | None) -> None:
    async with get_session_factory()() as session:
        project = await projects_service.create_project(
            session, slug, name, description, creator=None
        )
        print(f"project created: {project.id} ({project.slug})")


async def _resolve_project(session: AsyncSession, ref: str) -> ProjectModel:
    """`--project` accepts a UUID or a slug."""
    try:
        project = await session.get(ProjectModel, UUID(ref))
    except ValueError:
        result = await session.execute(select(ProjectModel).where(ProjectModel.slug == ref))
        project = result.scalar_one_or_none()
    if project is None:
        print(f"no project {ref}", file=sys.stderr)
        raise SystemExit(1)
    return project


async def _resolve_user(session: AsyncSession, email: str) -> UserModel:
    user = await provisioning_service.get_user_by_email(session, email.strip().lower())
    if user is None:
        print(f"no user with email {email}", file=sys.stderr)
        raise SystemExit(1)
    return user


async def _grant_project_member(project_ref: str, email: str, admin_email: str) -> None:
    """The CLI has no authenticated caller: `--admin-email` names the admin
    recorded as `granted_by_user_id` (DEC-0103, every grant keeps who gave it)."""
    async with get_session_factory()() as session:
        project = await _resolve_project(session, project_ref)
        user = await _resolve_user(session, email)
        admin = await _resolve_user(session, admin_email)
        if admin.role != Role.ADMIN.value:
            print(f"{admin_email} is not an admin", file=sys.stderr)
            raise SystemExit(1)
        _, created = await projects_service.grant_member(
            session, project.id, user.id, granted_by_user_id=admin.id
        )
    verb = "granted" if created else "already a member"
    print(f"{verb}: {user.email} -> {project.slug}")


async def _revoke_project_member(project_ref: str, email: str) -> None:
    async with get_session_factory()() as session:
        project = await _resolve_project(session, project_ref)
        user = await _resolve_user(session, email)
        removed = await projects_service.revoke_member(session, project.id, user.id)
    verb = "revoked" if removed else "not a member"
    print(f"{verb}: {user.email} -> {project.slug}")


async def _list_project_members(project_ref: str) -> None:
    async with get_session_factory()() as session:
        project = await _resolve_project(session, project_ref)
        members = await projects_service.list_members(session, project.id)
        users = await provisioning_service.users_by_id(session, {m.user_id for m in members})
    if not members:
        print("no member")
        return
    print(f"{'user_id':<36}  {'email':<32} granted_by")
    for member in members:
        email = users[member.user_id].email if member.user_id in users else "?"
        granted_by = member.granted_by_user_id or "system"
        print(f"{str(member.user_id):<36}  {email:<32} {granted_by}")


async def _expire_transfers() -> None:
    """Retention worker (roadmap etape 4.3, DEC-0020) — run on a schedule
    (e.g. VPS cron) rather than as an in-process scheduler dependency."""
    storage = get_storage()
    async with get_session_factory()() as session:
        expired = await transfers_service.expire_transfers(session, storage)
        for transfer in expired:
            print(f"transfer expired and deleted: {transfer.id} ({transfer.transfer_code})")
        print(f"{len(expired)} transfer(s) deleted")


async def _abort_stale_multipart_uploads(older_than_days: int, dry_run: bool) -> None:
    """Orphan-cleanup worker (DEC-0037, roadmap etape 7 P2) — run on a
    schedule, same model as `_expire_transfers`. Abandoning an in-progress
    multipart upload nobody resumed in `older_than_days` is never a data
    loss for the client (see `transfers_service.abort_stale_multipart_uploads`)."""
    storage = get_storage()
    stale = await transfers_service.abort_stale_multipart_uploads(
        storage, older_than_days, dry_run=dry_run
    )
    verb = "would abort" if dry_run else "aborted"
    for upload in stale:
        print(f"{verb} multipart upload: {upload['key']} ({upload['upload_id']})")
    print(f"{len(stale)} multipart upload(s) {'would be aborted' if dry_run else 'aborted'}")


async def _reconcile_builds() -> None:
    """Build catch-up worker (roadmap etape 9.1, DEC-0059) — replays recent
    GitHub workflow runs into `builds` + `build.*` events for every enabled
    integration, converging with webhook deliveries (same upsert key, same
    run-keyed event ids). Run on a schedule, same model as
    `_expire_transfers`: no in-process scheduler. Idempotent — a re-run
    touches no second row and emits no second event."""
    settings = get_settings()
    token = settings.github_token
    if not token:
        print("STUDIO_GITHUB_TOKEN is not set", file=sys.stderr)
        raise SystemExit(1)
    async with httpx.AsyncClient() as client:

        async def _fetch(repo_full_name: str, limit: int) -> list[dict[str, Any]]:
            return await github_service.fetch_workflow_runs(repo_full_name, token, limit, client)

        async with get_session_factory()() as session:
            builds = await github_service.reconcile_builds(
                session, _fetch, settings.github_reconcile_runs_limit
            )
    for build in builds:
        print(f"build reconciled: {build.id} (run {build.workflow_run_id}, {build.status})")
    print(f"{len(builds)} build(s) reconciled")


def main() -> None:
    parser = argparse.ArgumentParser(prog="studio-admin")
    sub = parser.add_subparsers(dest="command", required=True)

    bootstrap = sub.add_parser("bootstrap-admin", help="Create the first admin user")
    bootstrap.add_argument("--display-name", required=True)
    bootstrap.add_argument("--email", required=True)
    bootstrap.add_argument("--password", default=None, help="Initial dashboard password")

    user_parser = sub.add_parser("user", help="Manage users")
    user_sub = user_parser.add_subparsers(dest="user_command", required=True)
    user_create = user_sub.add_parser("create", help="Create a human user")
    user_create.add_argument("--display-name", required=True)
    user_create.add_argument("--email", required=True)
    user_create.add_argument("--role", required=True, choices=[role.value for role in Role])
    for action, help_text in (
        ("disable", "Block the user's sessions and machines until re-enabled"),
        ("enable", "Re-enable a disabled user"),
        ("revoke-sessions", "Invalidate every dashboard session of the user"),
    ):
        user_sub.add_parser(action, help=help_text).add_argument("--email", required=True)

    password_parser = sub.add_parser("set-password", help="Set a user's dashboard password")
    password_parser.add_argument("--email", required=True)
    password_source = password_parser.add_mutually_exclusive_group(required=True)
    password_source.add_argument("--password")
    password_source.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the password from stdin instead of an argument (keeps it out of ps/logs)",
    )

    machine_parser = sub.add_parser("machine", help="Manage machines")
    machine_sub = machine_parser.add_subparsers(dest="machine_command", required=True)
    machine_create = machine_sub.add_parser("create")
    machine_create.add_argument("--owner-email", required=True)
    machine_create.add_argument("--display-name", required=True)
    machine_revoke = machine_sub.add_parser("revoke")
    machine_revoke.add_argument("machine_id")
    machine_list = machine_sub.add_parser("list", help="List machines with their UUID")
    machine_list.add_argument("--owner-email", default=None)
    machine_sub.add_parser(
        "show",
        help="Resolve a machine (UUID/name/owner) from its token read on stdin",
    )

    project_parser = sub.add_parser("project", help="Manage projects")
    project_sub = project_parser.add_subparsers(dest="project_command", required=True)
    project_create = project_sub.add_parser("create")
    project_create.add_argument("--slug", required=True)
    project_create.add_argument("--name", required=True)
    project_create.add_argument("--description", default=None)
    project_grant = project_sub.add_parser("grant", help="Give a user access to a project")
    project_grant.add_argument("--project", required=True, help="Project UUID or slug")
    project_grant.add_argument("--email", required=True, help="User receiving access")
    project_grant.add_argument("--admin-email", required=True, help="Admin granting it")
    project_revoke = project_sub.add_parser("revoke", help="Remove a user's project access")
    project_revoke.add_argument("--project", required=True, help="Project UUID or slug")
    project_revoke.add_argument("--email", required=True)
    project_members = project_sub.add_parser("members", help="List a project's members")
    project_members.add_argument("--project", required=True, help="Project UUID or slug")

    transfer_parser = sub.add_parser("transfers", help="Manage transfers")
    transfer_sub = transfer_parser.add_subparsers(dest="transfer_command", required=True)
    transfer_sub.add_parser("expire", help="Delete expired transfers (DB + MinIO)")
    abort_stale = transfer_sub.add_parser(
        "abort-stale-multipart", help="Abort orphaned in-progress multipart uploads"
    )
    abort_stale.add_argument(
        "--older-than-days", type=int, default=get_settings().multipart_abandon_after_days
    )
    abort_stale.add_argument("--dry-run", action="store_true")

    builds_parser = sub.add_parser("builds", help="Manage builds")
    builds_sub = builds_parser.add_subparsers(dest="builds_command", required=True)
    builds_sub.add_parser(
        "reconcile",
        help="Replay recent GitHub workflow runs into builds + events (idempotent)",
    )

    args = parser.parse_args()

    try:
        if args.command == "bootstrap-admin":
            asyncio.run(_bootstrap_admin(args.display_name, args.email, args.password))
        elif args.command == "user" and args.user_command == "create":
            email = args.email.strip().lower()
            if not email or "@" not in email:
                print("error: --email must be a valid email address", file=sys.stderr)
                raise SystemExit(2)
            if not args.display_name.strip():
                print("error: --display-name must not be empty", file=sys.stderr)
                raise SystemExit(2)
            asyncio.run(_create_user(args.display_name, email, args.role))
        elif args.command == "user":
            asyncio.run(_update_user_state(args.user_command, args.email))
        elif args.command == "set-password":
            password = _read_password_from_stdin() if args.password_stdin else args.password
            asyncio.run(_set_password(args.email, password))
        elif args.command == "machine" and args.machine_command == "create":
            asyncio.run(_create_machine(args.owner_email, args.display_name))
        elif args.command == "machine" and args.machine_command == "revoke":
            asyncio.run(_revoke_machine(args.machine_id))
        elif args.command == "machine" and args.machine_command == "list":
            asyncio.run(_list_machines(args.owner_email))
        elif args.command == "machine" and args.machine_command == "show":
            asyncio.run(_show_machine_by_token(_read_secret_from_stdin("token")))
        elif args.command == "project" and args.project_command == "create":
            asyncio.run(_create_project(args.slug, args.name, args.description))
        elif args.command == "project" and args.project_command == "grant":
            asyncio.run(_grant_project_member(args.project, args.email, args.admin_email))
        elif args.command == "project" and args.project_command == "revoke":
            asyncio.run(_revoke_project_member(args.project, args.email))
        elif args.command == "project" and args.project_command == "members":
            asyncio.run(_list_project_members(args.project))
        elif args.command == "transfers" and args.transfer_command == "expire":
            asyncio.run(_expire_transfers())
        elif args.command == "transfers" and args.transfer_command == "abort-stale-multipart":
            asyncio.run(_abort_stale_multipart_uploads(args.older_than_days, args.dry_run))
        elif args.command == "builds" and args.builds_command == "reconcile":
            asyncio.run(_reconcile_builds())
    except HTTPException as exc:
        print(f"error: {exc.detail}", file=sys.stderr)
        exit_code = 2 if exc.status_code == status.HTTP_409_CONFLICT else 1
        raise SystemExit(exit_code) from exc


if __name__ == "__main__":
    main()
