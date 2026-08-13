"""create collection backfills table and mark backfilled mentions

Revision ID: ae6b3d1f4c90
Revises: 9d5a2c7f0e83
Create Date: 2026-08-13

Backfilling the weeks before signup (E03-S03), in two parts.

`collection_backfills` is a request and its receipt: the range a studio asked for, the
ceiling they confirmed it at, what it actually charged, and — the field the story is written
around — how far back it really got. It is a separate table rather than another trigger on
`collection_runs` because `uq_collection_run_one_pending_per_title` allows a title exactly
one pending cycle, so a backfill living there would mean asking for history stopped live
collection.

`mentions.is_backfilled` is the one thing a mention is allowed to say about how it arrived,
and it exists for the opposite reason there is no provider column. A provider split would be
a distinction the reader must never draw; this one they must: platform search depth means a
backfilled stretch is a sample of what was said rather than the record of it, so any chart
covering it has to be able to label the gap (concept note §6.4).

Existing rows backfill to `false`, which is not a guess — nothing before this migration
could collect a date range at all.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ae6b3d1f4c90"
down_revision: str | None = "9d5a2c7f0e83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# SQLAlchemy's `Enum` persists a Python enum's *name*, so the stored text is "QUEUED",
# not "queued". The partial index below filters on those.
_PENDING_PREDICATE = sa.text("status IN ('QUEUED', 'RUNNING')")


def upgrade() -> None:
    op.create_table(
        "collection_backfills",
        sa.Column("title_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("requested_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED",
                "RUNNING",
                "SUCCEEDED",
                "FAILED",
                "SKIPPED",
                name="collection_backfill_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("page_cap", sa.Integer(), nullable=False),
        sa.Column("estimated_calls", sa.Integer(), nullable=False),
        sa.Column("estimated_max_cost_usd", sa.Float(), nullable=False),
        sa.Column("pages_fetched", sa.Integer(), nullable=False),
        sa.Column("mentions_stored", sa.Integer(), nullable=False),
        sa.Column("mentions_already_known", sa.Integer(), nullable=False),
        sa.Column("unreadable", sa.Integer(), nullable=False),
        sa.Column("charged_cost_usd", sa.Float(), nullable=False),
        sa.Column("earliest_posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_depth_limited", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("has_reached_page_cap", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
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
        sa.ForeignKeyConstraint(["title_id"], ["titles.id"], ondelete="CASCADE"),
        # SET NULL rather than CASCADE: the spend happened, and the receipt has to outlive
        # the account of whoever agreed to it.
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_collection_backfills_title_id"),
        "collection_backfills",
        ["title_id"],
        unique=False,
    )
    op.create_index(
        "ix_collection_backfill_status_created_at",
        "collection_backfills",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_collection_backfill_title_created_at",
        "collection_backfills",
        ["title_id", "created_at"],
        unique=False,
    )
    # One pending backfill per title, enforced rather than checked. This is the only control
    # in the product that spends a lump of money on a button press, and a double-click on a
    # slow connection is the ordinary way to press it twice — where the failure is not a
    # duplicate row but a duplicate invoice.
    op.create_index(
        "uq_collection_backfill_one_pending_per_title",
        "collection_backfills",
        ["title_id"],
        unique=True,
        postgresql_where=_PENDING_PREDICATE,
        sqlite_where=_PENDING_PREDICATE,
    )

    op.add_column(
        "mentions",
        sa.Column("is_backfilled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("mentions", "is_backfilled")
    op.drop_index("uq_collection_backfill_one_pending_per_title", table_name="collection_backfills")
    op.drop_index("ix_collection_backfill_title_created_at", table_name="collection_backfills")
    op.drop_index("ix_collection_backfill_status_created_at", table_name="collection_backfills")
    op.drop_index(op.f("ix_collection_backfills_title_id"), table_name="collection_backfills")
    op.drop_table("collection_backfills")
