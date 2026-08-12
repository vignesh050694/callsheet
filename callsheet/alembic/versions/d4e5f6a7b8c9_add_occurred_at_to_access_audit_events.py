"""give access audit events their own ordering timestamp

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-12 15:40:00.000000

`created_at` carries a server default — `now()` on Postgres, which is transaction-start
time, and whole seconds on SQLite. Several access changes to one title inside the same
second therefore tie, and the tiebreak falls to a random UUID, so a title that was
granted, revoked, and granted again can read back in the wrong order. An audit log that
misreports its own sequence is worse than none.

`occurred_at` is set in Python at microsecond resolution and is the log's sort key.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Added nullable so existing rows can be backfilled, then tightened. `created_at` is
    # the best available truth for rows written before this column existed.
    op.add_column(
        "access_audit_events",
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE access_audit_events SET occurred_at = created_at WHERE occurred_at IS NULL")
    op.alter_column(
        "access_audit_events",
        "occurred_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.create_index(
        op.f("ix_access_audit_events_occurred_at"), "access_audit_events", ["occurred_at"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_access_audit_events_occurred_at"), table_name="access_audit_events")
    op.drop_column("access_audit_events", "occurred_at")
