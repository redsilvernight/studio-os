from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Sequence

from studio_client.tokens import KeyringTokenStore, origin_of


def login(argv: Sequence[str] | None = None) -> int:
    """Minimal enrollment gesture (sous-etape 6.1): paste the token printed
    by `studio-admin machine create` (or `POST /api/v1/machines`) once,
    store it in the OS keyring. Not the full CLI (sous-etape 6.5)."""
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


def main(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(login(argv))


if __name__ == "__main__":
    main()
