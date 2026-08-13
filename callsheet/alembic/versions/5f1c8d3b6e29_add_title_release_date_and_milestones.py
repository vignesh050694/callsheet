"""add title release date and campaign milestones

Revision ID: 5f1c8d3b6e29
Revises: 4e0b7c9a2d15
Create Date: 2026-08-11

`release_date` is NOT NULL, but it cannot be added that way to a table that may already
hold rows. It goes on nullable, existing titles are backfilled from the day they were set
up, and only then is the constraint applied. The backfill value is a placeholder, not a
fact — a title created before this migration has no recorded release date, and the setup
date is simply the only date the row carries. Any title that survives this migration
should have its release date confirmed by its owner.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5f1c8d3b6e29"
down_revision: str | None = "4e0b7c9a2d15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("titles", sa.Column("release_date", sa.Date(), nullable=True))
    # `CAST(created_at AS DATE)` on a timestamptz resolves in the *session's* timezone,
    # so the same row backfills to different calendar days depending on how the
    # connection happens to be configured. Pinned to UTC, which is what is stored.
    op.execute(
        "UPDATE titles SET release_date = (created_at AT TIME ZONE 'UTC')::date "
        "WHERE release_date IS NULL"
    )
    op.alter_column("titles", "release_date", existing_type=sa.Date(), nullable=False)

    op.create_table(
        "title_milestones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("normalized_name", sa.String(length=120), nullable=False),
        sa.Column("occurs_on", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["title_id"], ["titles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "title_id",
            "normalized_name",
            "occurs_on",
            name="uq_title_milestone_name_date",
        ),
    )
    op.create_index(
        op.f("ix_title_milestones_title_id"),
        "title_milestones",
        ["title_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_title_milestones_title_id"), table_name="title_milestones")
    op.drop_table("title_milestones")
    op.drop_column("titles", "release_date")
