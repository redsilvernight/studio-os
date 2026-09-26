"""Account states (A3, DU-0/A): normalized, case-insensitively unique emails.

Preflight (blocking): no two users may share an email once trimmed and
lower-cased — the migration refuses to pick a survivor and lists the
colliding user ids for an operator to merge first. Upgrade then rewrites
every email to its normalized form (the same `strip().lower()` as
`studio_api.services.provisioning.normalize_email`) and replaces the
`uq_users_email` constraint with the unique index `uq_users_email_lower` on
`lower(email)`. Account state columns come from 0015 and are left
untouched: existing users stay active and verified.

Downgrade restores `uq_users_email`; emails stay normalized (the original
casing is not kept — lower-casing is not reversible, and harmless).

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-26
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")


def _normalize(email: str) -> str:
    return email.strip().lower()


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, email FROM users ORDER BY created_at, id")).fetchall()
    groups: dict[str, list[str]] = defaultdict(list)
    for user_id, email in rows:
        groups[_normalize(email)].append(str(user_id))
    duplicates = {email: ids for email, ids in groups.items() if len(ids) > 1}
    if duplicates:
        raise RuntimeError(
            "0016 preflight: users sharing an email once normalized, merge them before "
            "migrating: " + "; ".join(",".join(ids) for ids in duplicates.values())
        )

    rewritten = 0
    for user_id, email in rows:
        normalized = _normalize(email)
        if normalized != email:
            bind.execute(
                sa.text("UPDATE users SET email = :email WHERE id = :id"),
                {"email": normalized, "id": user_id},
            )
            rewritten += 1
    log.info("0016 normalization: %s of %s emails rewritten", rewritten, len(rows))

    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)


def downgrade() -> None:
    op.drop_index("uq_users_email_lower", table_name="users")
    op.create_unique_constraint("uq_users_email", "users", ["email"])
