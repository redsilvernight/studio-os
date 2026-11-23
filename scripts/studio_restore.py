"""Restore a studio export archive into a new studio.

    uv run python scripts/studio_restore.py <archive.zip> <owner-email>

Uses the API's own settings (database, object storage). The archive must be
decrypted first; the new studio is owned by the account with `<owner-email>`.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import select
from studio_api.db.models.user import UserModel
from studio_api.db.session import get_session_factory
from studio_api.services.studio_restore import (
    RestoreError,
    count_studio_rows,
    restore_studio_archive,
)
from studio_api.storage.provider import get_storage


async def _run(archive: Path, email: str) -> int:
    async with get_session_factory()() as session:
        owner = (
            await session.execute(select(UserModel).where(UserModel.email == email))
        ).scalar_one_or_none()
        if owner is None:
            print(f"compte introuvable: {email}")
            return 2
        try:
            result = await restore_studio_archive(
                session, get_storage(), archive.read_bytes(), owner
            )
        except RestoreError as error:
            await session.rollback()
            print(f"restauration refusée: {error}")
            return 3
        await session.commit()
        counts = await count_studio_rows(session, result.studio.id)
    print(f"studio restauré: {result.studio.id} ({result.studio.slug})")
    print(f"comptages: {counts}; fichiers ignorés: {result.skipped_files}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("owner_email")
    args = parser.parse_args()
    return asyncio.run(_run(args.archive, args.owner_email))


if __name__ == "__main__":
    raise SystemExit(main())
