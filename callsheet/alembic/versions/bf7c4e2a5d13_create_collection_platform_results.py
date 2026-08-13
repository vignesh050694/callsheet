"""create collection platform results table

Revision ID: bf7c4e2a5d13
Revises: ae6b3d1f4c90
Create Date: 2026-08-13

Per-platform collection outcomes (E03-S05).

`collection_runs` records one outcome for all four platforms at once, which answers "is this
title collecting" and cannot answer "is Instagram collecting" — and a cycle in which three
platforms worked and one failed is a success by every counter on that table. That is exactly
the shape of the failure this story exists to surface, so it needs its own axis.

A log rather than a current-state row per platform. **Repeated** failure is the alerting
signal the story's Notes ask for — one failed poll is a blip, six in a row is an outage —
and a snapshot cannot tell them apart. It also lets a studio see when a gap opened rather
than only that one is open.

No backfill of existing rows, and that is the honest choice rather than a shortcut. Cycles
before this migration genuinely did not record which platforms succeeded, and inventing
"probably X, probably fine" would put a fabricated last-successful-collection time on the one
screen whose entire purpose is telling the truth about coverage. Those titles read as
`pending` for a platform until their next cycle, which is at most one interval away.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "bf7c4e2a5d13"
down_revision: str | None = "ae6b3d1f4c90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "collection_platform_results",
        sa.Column("collection_run_id", sa.Uuid(), nullable=False),
        sa.Column("title_id", sa.Uuid(), nullable=False),
        sa.Column(
            "platform",
            sa.Enum("X", "INSTAGRAM", "REDDIT", "YOUTUBE", name="platform", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "SUCCEEDED",
                "UNAVAILABLE",
                "FAILED",
                name="platform_collection_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("pages_fetched", sa.Integer(), nullable=False),
        sa.Column("mentions_stored", sa.Integer(), nullable=False),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["collection_run_id"], ["collection_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["title_id"], ["titles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_collection_platform_results_title_id"),
        "collection_platform_results",
        ["title_id"],
        unique=False,
    )
    # Every question this story asks is "this title, this platform, most recent first".
    op.create_index(
        "ix_collection_platform_result_title_platform_finished",
        "collection_platform_results",
        ["title_id", "platform", "finished_at"],
        unique=False,
    )
    op.create_index(
        "ix_collection_platform_result_run",
        "collection_platform_results",
        ["collection_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_collection_platform_result_run", table_name="collection_platform_results"
    )
    op.drop_index(
        "ix_collection_platform_result_title_platform_finished",
        table_name="collection_platform_results",
    )
    op.drop_index(
        op.f("ix_collection_platform_results_title_id"),
        table_name="collection_platform_results",
    )
    op.drop_table("collection_platform_results")
