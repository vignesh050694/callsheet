"""remember refused alias suggestions, and tell retroactive matches apart

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-12 17:10:00.000000

Two changes, both for alias discovery (E02-S04).

`title_alias_rejections` is where a "no" lives. Suggestions themselves are never stored —
they are re-mined from the corpus on every read, because what makes one worth showing is
how many posts carry it and that changes with every poll. A rejection has nowhere else to
go, and without it the same seven organic hashtags come back after every cycle.

`mention_query_matches.match_source` separates a variant that ran as a query and was paid
for from a term approved after the fact and checked against posts already collected. Both
are worth recording; adding them together would credit a term with finding posts it never
fetched. Every row that existed before this column was a collection hit, which is what the
server default backfills them as.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `native_enum=False` on both, matching the models: these compile to a plain VARCHAR, so
# adding a member later is a code change rather than a migration on every consumer.
_ALIAS_CANDIDATE_KIND = sa.Enum(
    "HASHTAG", "NAME_VARIANT", name="alias_candidate_kind", native_enum=False
)
_MATCH_SOURCE = sa.Enum(
    "COLLECTION", "RETROACTIVE", name="mention_query_match_source", native_enum=False
)


def upgrade() -> None:
    op.create_table(
        "title_alias_rejections",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "title_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("titles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", _ALIAS_CANDIDATE_KIND, nullable=False),
        sa.Column("value", sa.String(300), nullable=False),
        sa.Column("folded_value", sa.String(300), nullable=False),
        sa.Column(
            "rejected_by_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("title_id", "folded_value", name="uq_title_alias_rejection_folded"),
    )
    op.create_index(
        op.f("ix_title_alias_rejections_title_id"), "title_alias_rejections", ["title_id"]
    )

    # NOT NULL with a server default in one step, so no window exists where a row can be
    # written without a source. The stored form is the enum member *name*, which is what
    # SQLAlchemy persists — 'collection' would be silently unreadable.
    op.add_column(
        "mention_query_matches",
        sa.Column(
            "match_source",
            _MATCH_SOURCE,
            nullable=False,
            server_default="COLLECTION",
        ),
    )


def downgrade() -> None:
    # Retroactive attribution rows have no home in the older schema, and leaving them
    # would misreport every affected term as having been found by a query that never ran.
    # Removed rather than kept: they are derived from stored posts, so re-approving the
    # term rebuilds them without a provider call.
    op.execute("DELETE FROM mention_query_matches WHERE match_source = 'RETROACTIVE'")
    op.drop_column("mention_query_matches", "match_source")

    op.drop_index(op.f("ix_title_alias_rejections_title_id"), table_name="title_alias_rejections")
    op.drop_table("title_alias_rejections")
