"""create mention analyses table

Revision ID: 7b3e0a5d8c61
Revises: 6a2d9e4f7c58
Create Date: 2026-08-12

Derived fields live apart from both the mention and its raw payload, keyed by
`(mention_id, pipeline_version)`. Reprocessing under a new version therefore inserts
beside the old rows rather than over them: the dashboard keeps reading the version it
trusts while a long re-run proceeds, and rolling back a bad model is a change of which
version is read, not another pass over the corpus.

Every judgement column is nullable because the pipeline ships in pieces (E04-S01 through
S04). Null means "this version did not judge that", which is the honest reading — a
default sentiment would be a number nothing stands behind.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7b3e0a5d8c61"
down_revision: str | None = "6a2d9e4f7c58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mention_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mention_id", sa.Uuid(), nullable=False),
        sa.Column("title_id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_version", sa.String(length=60), nullable=False),
        sa.Column("detected_language", sa.String(length=60), nullable=True),
        sa.Column("language_confidence", sa.Float(), nullable=True),
        sa.Column("is_code_mixed", sa.Boolean(), nullable=True),
        sa.Column("account_type", sa.String(length=40), nullable=True),
        sa.Column("account_type_confidence", sa.Float(), nullable=True),
        sa.Column("sentiment_label", sa.String(length=30), nullable=True),
        sa.Column("sentiment_confidence", sa.Float(), nullable=True),
        sa.Column("themes", sa.JSON(), nullable=False),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(["mention_id"], ["mentions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["title_id"], ["titles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "mention_id",
            "pipeline_version",
            name="uq_mention_analysis_mention_pipeline_version",
        ),
    )
    op.create_index(
        op.f("ix_mention_analyses_mention_id"), "mention_analyses", ["mention_id"]
    )
    op.create_index(op.f("ix_mention_analyses_title_id"), "mention_analyses", ["title_id"])
    op.create_index(
        "ix_mention_analysis_title_pipeline",
        "mention_analyses",
        ["title_id", "pipeline_version"],
    )


def downgrade() -> None:
    op.drop_index("ix_mention_analysis_title_pipeline", table_name="mention_analyses")
    op.drop_index(op.f("ix_mention_analyses_title_id"), table_name="mention_analyses")
    op.drop_index(op.f("ix_mention_analyses_mention_id"), table_name="mention_analyses")
    op.drop_table("mention_analyses")
