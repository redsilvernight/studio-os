"""Server-side provisioning CLI (DEC-0011). Run on the VPS, never exposed over
HTTP: bootstrapping the first admin user has no machine token to authenticate
against, and SSH access to the VPS is already the trust root for this stack's
other secrets (see docker/docker-compose.yml)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID

from fastapi import HTTPException

from studio_api.db.session import get_session_factory
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service


async def _bootstrap_admin(display_name: str, email: str) -> None:
    async with get_session_factory()() as session:
        user = await provisioning_service.bootstrap_admin(session, display_name, email)
        print(f"admin user created: {user.id} ({user.email})")


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


async def _create_project(slug: str, name: str, description: str | None) -> None:
    async with get_session_factory()() as session:
        project = await projects_service.create_project(session, slug, name, description)
        print(f"project created: {project.id} ({project.slug})")


def main() -> None:
    parser = argparse.ArgumentParser(prog="studio-admin")
    sub = parser.add_subparsers(dest="command", required=True)

    bootstrap = sub.add_parser("bootstrap-admin", help="Create the first admin user")
    bootstrap.add_argument("--display-name", required=True)
    bootstrap.add_argument("--email", required=True)

    machine_parser = sub.add_parser("machine", help="Manage machines")
    machine_sub = machine_parser.add_subparsers(dest="machine_command", required=True)
    machine_create = machine_sub.add_parser("create")
    machine_create.add_argument("--owner-email", required=True)
    machine_create.add_argument("--display-name", required=True)
    machine_revoke = machine_sub.add_parser("revoke")
    machine_revoke.add_argument("machine_id")

    project_parser = sub.add_parser("project", help="Manage projects")
    project_sub = project_parser.add_subparsers(dest="project_command", required=True)
    project_create = project_sub.add_parser("create")
    project_create.add_argument("--slug", required=True)
    project_create.add_argument("--name", required=True)
    project_create.add_argument("--description", default=None)

    args = parser.parse_args()

    try:
        if args.command == "bootstrap-admin":
            asyncio.run(_bootstrap_admin(args.display_name, args.email))
        elif args.command == "machine" and args.machine_command == "create":
            asyncio.run(_create_machine(args.owner_email, args.display_name))
        elif args.command == "machine" and args.machine_command == "revoke":
            asyncio.run(_revoke_machine(args.machine_id))
        elif args.command == "project" and args.project_command == "create":
            asyncio.run(_create_project(args.slug, args.name, args.description))
    except HTTPException as exc:
        print(f"error: {exc.detail}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
