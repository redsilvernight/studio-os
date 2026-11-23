"""Break-glass exception access (DEC-0384).

`break_glass_requests` carries one operator request: who asked, why, for which
declared scope (`metadata` or `support`, never content), and the owner's
decision with a window capped at 24 hours.

`break_glass_audit` is the client-visible journal: one row per transition
(`requested`, `approved`, `denied`, `expired`, `revoked`), plus who acted and
when. A trigger refuses UPDATE and DELETE, so the journal is append-only. No
content column exists in either table.

Revision ID: 0055
Revises: 0053
Create Date: 2026-11-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0055"
down_revision: str | None = "0053"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "break_glass_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "studio_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("studios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operator_ref", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("status", sa.String(), server_default="requested", nullable=False),
        sa.Column(
            "decided_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "scope IN ('metadata', 'support')", name="ck_break_glass_requests_scope"
        ),
        sa.CheckConstraint(
            "status IN ('requested', 'approved', 'denied', 'expired', 'revoked')",
            name="ck_break_glass_requests_status",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR "
            "(decided_at IS NOT NULL AND expires_at <= decided_at + interval '24 hours')",
            name="ck_break_glass_requests_window",
        ),
    )
    op.create_index("ix_break_glass_requests_studio_id", "break_glass_requests", ["studio_id"])
    op.create_index(
        "ix_break_glass_requests_status", "break_glass_requests", ["studio_id", "status"]
    )

    op.create_table(
        "break_glass_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("studio_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "event IN ('requested', 'approved', 'denied', 'expired', 'revoked')",
            name="ck_break_glass_audit_event",
        ),
    )
    op.create_index("ix_break_glass_audit_studio_at", "break_glass_audit", ["studio_id", "at"])
    op.create_index("ix_break_glass_audit_request_id", "break_glass_audit", ["request_id"])

    op.execute(
        """
        CREATE FUNCTION break_glass_audit_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'break_glass_audit is append-only (% refused)', TG_OP;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER break_glass_audit_no_update_delete
        BEFORE UPDATE OR DELETE ON break_glass_audit
        FOR EACH ROW EXECUTE FUNCTION break_glass_audit_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS break_glass_audit_no_update_delete ON break_glass_audit")
    op.execute("DROP FUNCTION IF EXISTS break_glass_audit_append_only()")
    op.drop_index("ix_break_glass_audit_request_id", table_name="break_glass_audit")
    op.drop_index("ix_break_glass_audit_studio_at", table_name="break_glass_audit")
    op.drop_table("break_glass_audit")
    op.drop_index("ix_break_glass_requests_status", table_name="break_glass_requests")
    op.drop_index("ix_break_glass_requests_studio_id", table_name="break_glass_requests")
    op.drop_table("break_glass_requests")
