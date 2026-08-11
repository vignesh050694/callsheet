"""create mentions and raw payload tables

Revision ID: 6a2d9e4f7c58
Revises: 5f1c8d3b6e29
Create Date: 2026-08-11

Two tables rather than one wide one. `mentions` is the corpus every later read goes
through and carries no provider column, so a chart cannot split a title's trend at the
moment operations swapped endpoints. `mention_raw_payloads` holds what was actually paid
for, verbatim, with the provenance the normalised row refuses to carry.

`payload` is `sa.JSON` rather than `JSONB`. Nothing queries inside it — it is read whole,
by id, when a corpus is reprocessed (E03-S04) — and `sa.JSON` is the one form that
compiles on both Postgres and the SQLite the test suite runs against. Moving it to JSONB
is a later migration if a query ever needs to reach inside a payload.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6a2d9e4f7c58"
down_revision: str | None = "5f1c8d3b6e29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Matches `native_enum=False` on the model: a VARCHAR with no CHECK constraint, so adding
# a platform later is a code change rather than a migration (the same choice title term
# types made in 4e0b7c9a2d15).
_PLATFORM = sa.String(length=9)


def upgrade() -> None:
    op.create_table(
        "mentions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title_id", sa.Uuid(), nullable=False),
        sa.Column("platform", _PLATFORM, nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("permalink", sa.String(length=2048), nullable=True),
        sa.Column("author_handle", sa.String(length=255), nullable=False),
        sa.Column("author_display_name", sa.String(length=255), nullable=False),
        sa.Column("author_follower_count", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("platform_reported_language", sa.String(length=35), nullable=True),
        sa.Column("hashtags", sa.JSON(), nullable=False),
        sa.Column("like_count", sa.Integer(), nullable=True),
        sa.Column("reply_count", sa.Integer(), nullable=True),
        sa.Column("repost_count", sa.Integer(), nullable=True),
        sa.Column("quote_count", sa.Integer(), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=True),
        sa.Column("bookmark_count", sa.Integer(), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
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
            "platform",
            "external_id",
            name="uq_mention_title_platform_external_id",
        ),
    )
    op.create_index(op.f("ix_mentions_title_id"), "mentions", ["title_id"])
    op.create_index(
        "ix_mention_title_posted_at", "mentions", ["title_id", "posted_at"]
    )

    op.create_table(
        "mention_raw_payloads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title_id", sa.Uuid(), nullable=False),
        sa.Column("mention_id", sa.Uuid(), nullable=True),
        sa.Column("platform", _PLATFORM, nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("endpoint_key", sa.String(length=120), nullable=False),
        sa.Column("adapter_version", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("normalization_error", sa.String(length=500), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(["mention_id"], ["mentions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mention_id"),
        sa.UniqueConstraint(
            "title_id",
            "platform",
            "external_id",
            name="uq_mention_raw_payload_title_platform_external_id",
        ),
    )
    op.create_index(
        op.f("ix_mention_raw_payloads_title_id"), "mention_raw_payloads", ["title_id"]
    )
    op.create_index(
        "ix_mention_raw_payload_endpoint",
        "mention_raw_payloads",
        ["endpoint_key", "collected_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_mention_raw_payload_endpoint", table_name="mention_raw_payloads")
    op.drop_index(
        op.f("ix_mention_raw_payloads_title_id"), table_name="mention_raw_payloads"
    )
    op.drop_table("mention_raw_payloads")
    op.drop_index("ix_mention_title_posted_at", table_name="mentions")
    op.drop_index(op.f("ix_mentions_title_id"), table_name="mentions")
    op.drop_table("mentions")
