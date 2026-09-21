"""Throwaway Studio OS API stack for the P2 Desktop gate (never real data).

Creates a scratch PostgreSQL database, migrates it, bootstraps a random
admin, starts the API on a loopback port with the Desktop origin as the ONLY
CORS origin, prints one JSON "ready" line, then waits for stdin to close and
tears everything down (server stopped, database dropped).

    uv run --all-packages python desktop/e2e/gate_stack.py

Environment (all optional):
    STUDIO_GATE_PG_ADMIN_URL  postgresql://user:pass@host:port/postgres  (needs CREATEDB)
    STUDIO_GATE_PORT          API port (default 8765)
    STUDIO_GATE_CORS_ORIGINS  value for STUDIO_CORS_ORIGINS (default http://tauri.localhost)
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import asyncpg

REPO = Path(__file__).resolve().parents[2]
API_DIR = REPO / "services" / "api"
PG_ADMIN_URL = os.environ.get(
    "STUDIO_GATE_PG_ADMIN_URL", "postgresql://studio:studio@localhost:5432/postgres"
)
PORT = int(os.environ.get("STUDIO_GATE_PORT", "8765"))
CORS = os.environ.get("STUDIO_GATE_CORS_ORIGINS", "http://tauri.localhost")
DB_NAME = f"studio_desktop_gate_{secrets.token_hex(4)}"
ADMIN_EMAIL = "gate-admin@example.test"
ADMIN_PASSWORD = secrets.token_urlsafe(18)  # random per run, never persisted
PROJECT_SLUG = "desktop-gate"


def _db_url() -> str:
    base = PG_ADMIN_URL.rsplit("/", 1)[0]
    return base.replace("postgresql://", "postgresql+asyncpg://", 1) + f"/{DB_NAME}"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        STUDIO_DATABASE_URL=_db_url(),
        STUDIO_CORS_ORIGINS=CORS,
        STUDIO_JWT_SECRET=secrets.token_urlsafe(32),
        STUDIO_RATE_LIMIT_REQUESTS_PER_MINUTE="6000",
        STUDIO_RATE_LIMIT_BURST="600",
    )
    return env


async def _create_db() -> None:
    conn = await asyncpg.connect(PG_ADMIN_URL)
    try:
        await conn.execute(f'CREATE DATABASE "{DB_NAME}"')
    finally:
        await conn.close()


async def _drop_db() -> None:
    conn = await asyncpg.connect(PG_ADMIN_URL)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)')
    finally:
        await conn.close()


def _run(args: list[str], env: dict[str, str], cwd: Path, stdin: str | None = None) -> str:
    done = subprocess.run(
        args, env=env, cwd=cwd, input=stdin, text=True, capture_output=True, check=False
    )
    if done.returncode != 0:
        sys.stderr.write(done.stderr[-2000:])
        raise SystemExit(f"step failed: {' '.join(args[:4])}")
    return done.stdout


def _wait_ready(timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/openapi.json", timeout=2):
                return
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    raise SystemExit("API did not become ready")


def main() -> int:
    asyncio.run(_create_db())
    server: subprocess.Popen[bytes] | None = None
    try:
        env = _env()
        py = sys.executable
        _run(
            [py, "-m", "alembic", "-c", str(API_DIR / "alembic.ini"), "upgrade", "head"],
            env,
            API_DIR,
        )
        admin = [py, "-m", "studio_api.admin_cli"]
        created = _run(
            [*admin, "bootstrap-admin", "--display-name", "Gate Admin", "--email", ADMIN_EMAIL],
            env,
            API_DIR,
        )
        admin_id = created.split("admin user created:")[1].split()[0]
        _run(
            [*admin, "set-password", "--email", ADMIN_EMAIL, "--password-stdin"],
            env,
            API_DIR,
            stdin=ADMIN_PASSWORD + "\n",
        )
        machine_out = _run(
            [
                *admin,
                "machine",
                "create",
                "--owner-email",
                ADMIN_EMAIL,
                "--display-name",
                "gate-machine",
            ],
            env,
            API_DIR,
        )
        machine_token = machine_out.split("never shown again):")[1].split()[0]
        _run(
            [*admin, "project", "create", "--slug", PROJECT_SLUG, "--name", "Desktop gate"],
            env,
            API_DIR,
        )
        server = subprocess.Popen(
            [
                py,
                "-m",
                "uvicorn",
                "studio_api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(PORT),
            ],
            env=env,
            cwd=API_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_ready()
        print(
            json.dumps(
                {
                    "ready": True,
                    "api": f"http://127.0.0.1:{PORT}",
                    "cors_origins": CORS,
                    "email": ADMIN_EMAIL,
                    "password": ADMIN_PASSWORD,
                    "project": PROJECT_SLUG,
                    "admin_id": admin_id,
                    "machine_token": machine_token,
                    "database": DB_NAME,
                }
            ),
            flush=True,
        )
        sys.stdin.read()  # the harness closes stdin to end the stack
        return 0
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
        asyncio.run(_drop_db())


if __name__ == "__main__":
    raise SystemExit(main())
