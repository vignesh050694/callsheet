"""add cadence phase to collection runs

Revision ID: 9d5a2c7f0e83
Revises: 8c4f1b6e9d72
Create Date: 2026-08-12

Two columns recording *why* a cycle was scheduled at the rate it was (E03-S02).

`polls_per_day` already said how hard a cycle polled. It could not say whether that was the
calendar's doing or a reaction to a volume spike, and those are the same number with very
different implications for a bill nobody expected.

Existing rows are backfilled as `CAMPAIGN`, unescalated, which is not a guess: E03-S01
polled every title at one flat rate and that rate was the concept note's campaign rate of
12/day. Every run already in this table was scheduled at exactly that.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9d5a2c7f0e83"
down_revision: str | None = "8c4f1b6e9d72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CADENCE_PHASE = sa.Enum(
    "DORMANT",
    "CAMPAIGN",
    "RELEASE_SURGE",
    name="cadence_phase",
    native_enum=False,
)


def upgrade() -> None:
    op.add_column(
        "collection_runs",
        sa.Column(
            "cadence_phase",
            _CADENCE_PHASE,
            nullable=False,
            server_default="CAMPAIGN",
        ),
    )
    op.add_column(
        "collection_runs",
        sa.Column(
            "is_volume_escalated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("collection_runs", "is_volume_escalated")
    op.drop_column("collection_runs", "cadence_phase")
