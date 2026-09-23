"""Temporary real-OS-keyring machine-credential fixture for the P12 onboarding
E2E (`scripts/onboarding-walkthrough.mjs`).

The onboarding wizard's "verification" step (identity.get_view) checks
KeyringTokenStore directly, not the env-first resolve_token() chain the
daemon uses for API auth - so exercising that step for real requires a
credential actually present in the OS keyring. This fixture writes/removes
one entry there, through the same KeyringTokenStore Studi'OS itself uses,
strictly scoped to a single disposable loopback gate-stack origin.

A marker file (its path given via STUDIO_P12_KEYRING_MARKER) is the proof of
provenance: `create` refuses to touch a pre-existing keyring entry unless the
marker proves this fixture wrote it, and `cleanup` verifies removal.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from studio_client.tokens import KeyringTokenStore

SERVICE = "studio-os"


def _marker_path() -> Path:
    marker = os.environ.get("STUDIO_P12_KEYRING_MARKER")
    if not marker:
        raise SystemExit("STUDIO_P12_KEYRING_MARKER not set")
    return Path(marker)


def _is_loopback_origin(origin: str) -> bool:
    return urlparse(origin).hostname in ("127.0.0.1", "localhost", "::1")


def cmd_create(origin: str) -> None:
    if not _is_loopback_origin(origin):
        raise SystemExit(f"refusing: {origin!r} is not a loopback P12 test origin")
    token = os.environ.get("P12_MACHINE_TOKEN")
    if not token:
        raise SystemExit("P12_MACHINE_TOKEN not set")

    store = KeyringTokenStore(SERVICE)
    marker = _marker_path()
    existing_marker = marker.exists()
    existing_entry = store.get_token(origin) is not None

    if existing_entry and not existing_marker:
        raise SystemExit(
            f"refusing: a keyring entry already exists for {SERVICE}/{origin} "
            "with no P12 marker proving provenance - not touching it"
        )
    if existing_entry and existing_marker:
        store.clear_token(origin)
        marker.unlink()
        print("cleared stale P12 residue from an interrupted prior run", file=sys.stderr)
    elif existing_marker and not existing_entry:
        marker.unlink()

    marker.write_text(
        json.dumps(
            {"service": SERVICE, "account": origin, "purpose": "P12 onboarding-walkthrough fixture"}
        ),
        encoding="utf-8",
    )
    store.set_token(origin, token)
    print("created", file=sys.stderr)


def cmd_cleanup(origin: str) -> None:
    store = KeyringTokenStore(SERVICE)
    store.clear_token(origin)
    remaining = store.get_token(origin)
    marker = _marker_path()
    if marker.exists():
        marker.unlink()
    if remaining is not None:
        raise SystemExit(
            f"cleanup verification FAILED: {SERVICE}/{origin} still present in keyring"
        )
    print("cleaned up and verified absent", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["create", "cleanup"])
    parser.add_argument("--origin", required=True)
    args = parser.parse_args()
    (cmd_create if args.action == "create" else cmd_cleanup)(args.origin)


if __name__ == "__main__":
    main()
