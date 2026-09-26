"""A5 enrollment E2E helper (`scripts/a5-enroll-e2e.mjs`): inspects what the
real Desktop daemon wrote into the real OS keyring, without ever printing it.

    check-absent --origin O          refuse to run over a pre-existing entry
    probe --origin O --other ID --profile DIR
                                     use the stored credential: owner, visible
                                     projects, access to another project, and
                                     whether any secret leaked into DIR
    cleanup --origin O               remove the entry and verify it is gone

Loopback origins only (disposable gate stack).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from studio_client.tokens import KeyringTokenStore

SERVICE = "studio-os"
_JWT = re.compile(rb"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")


def _loopback(origin: str) -> str:
    if urlparse(origin).hostname not in ("127.0.0.1", "localhost"):
        raise SystemExit(f"refusing: {origin!r} is not a loopback test origin")
    return origin


def _get(origin: str, path: str, token: str) -> tuple[int, object]:
    request = urllib.request.Request(
        f"{origin}{path}", headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, None


def _leaks(root: Path, credential: str) -> list[str]:
    found: list[str] = []
    needle = credential.encode()
    for path in root.rglob("*"):
        if not path.is_file() or path.stat().st_size > 20_000_000:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if needle in data or _JWT.search(data):
            found.append(str(path.relative_to(root)))
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["check-absent", "probe", "cleanup"])
    parser.add_argument("--origin", required=True)
    parser.add_argument("--other")
    parser.add_argument("--profile")
    args = parser.parse_args()
    origin = _loopback(args.origin)
    store = KeyringTokenStore(SERVICE)

    if args.action == "check-absent":
        if store.get_token(origin) is not None:
            raise SystemExit(f"refusing: a keyring entry already exists for {SERVICE}/{origin}")
        return 0

    if args.action == "cleanup":
        store.clear_token(origin)
        if store.get_token(origin) is not None:
            raise SystemExit("cleanup verification FAILED")
        return 0

    credential = store.get_token(origin)
    result: dict[str, object] = {"stored": credential is not None}
    if credential is not None:
        status, me = _get(origin, "/api/v1/machines/me", credential)
        result["me_status"] = status
        result["owner_user_id"] = (me or {}).get("owner_user_id") if isinstance(me, dict) else None
        status, projects = _get(origin, "/api/v1/projects", credential)
        result["projects_status"] = status
        result["project_slugs"] = sorted(p["slug"] for p in projects or [])
        if args.other:
            result["other_status"] = _get(origin, f"/api/v1/projects/{args.other}", credential)[0]
        if args.profile:
            result["leaks"] = _leaks(Path(args.profile), credential)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
