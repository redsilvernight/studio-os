"""Events without a project for Studio-scope library (contract v2).

`events.project_id` becomes nullable; a `NULL` row is a Studio-wide
`library.*` event, visible to every authenticated principal. The new
`ck_events_project_scope` CHECK guarantees the converse at the database
level: only `library.*` types may have no project. The CHECK is added
`NOT VALID` then validated in a second statement, so a populated table
is never held under an `ACCESS EXCLUSIVE` lock for the whole scan.

Reversible: the downgrade drops the CHECK and restores `NOT NULL`. It
requires no project-less row to exist (a Studio event emitted after this
upgrade); on a database that already carries some, delete or reassign
them first — the downgrade then fails loudly instead of silently
rewriting history.

Revision ID: 0043
Revises: 0042
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"


def upgrade() -> None:
    op.alter_column("events", "project_id", existing_type=sa.UUID(), nullable=True)
    op.execute(
        "ALTER TABLE events ADD CONSTRAINT ck_events_project_scope "
        "CHECK ((project_id IS NOT NULL) OR (event_type LIKE 'library.%')) NOT VALID"
    )
    # VALIDATE in its own transaction: it only takes SHARE UPDATE EXCLUSIVE,
    # so writes continue while the populated table is scanned.
    with op.get_context().autocommit_block():
        op.execute("ALTER TABLE events VALIDATE CONSTRAINT ck_events_project_scope")


def downgrade() -> None:
    op.execute("ALTER TABLE events DROP CONSTRAINT ck_events_project_scope")
    op.alter_column("events", "project_id", existing_type=sa.UUID(), nullable=False)
