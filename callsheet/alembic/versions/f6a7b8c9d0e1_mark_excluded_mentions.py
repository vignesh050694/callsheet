"""mark mentions an exclusion rule disowned, instead of deleting them

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-12 18:20:00.000000

An exclusion term (E02-S05) removes a post from every count and chart, historic ones
included. It does not remove the row: the payload was paid for, and a studio can change
their mind about what belongs to their film — so the rule marks, and lifting it unmarks.

`excluded_by_term` carries *which* rule disowned the post rather than a bare boolean,
because "removed by #DareDevil" is a number somebody can audit and "not counted" is one
they have to trust. Null is the normal state and means the post counts, so no backfill is
needed: everything collected before exclusions could be applied did count.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mentions", sa.Column("excluded_by_term", sa.String(300), nullable=True))
    op.add_column("mentions", sa.Column("excluded_at", sa.DateTime(timezone=True), nullable=True))
    # "Everything this one rule removed" — the read that lifting an exclusion runs.
    op.create_index(
        "ix_mention_title_excluded_by_term", "mentions", ["title_id", "excluded_by_term"]
    )


def downgrade() -> None:
    # Dropping the columns is enough, and is the right answer rather than a data loss.
    # Every disowned post becomes counted again, which is exactly what the older schema
    # meant by holding it: it had no way to express the exclusion. Nothing is destroyed —
    # re-applying the rule after an upgrade re-marks the same rows from stored text,
    # without a provider call.
    op.drop_index("ix_mention_title_excluded_by_term", table_name="mentions")
    op.drop_column("mentions", "excluded_at")
    op.drop_column("mentions", "excluded_by_term")
