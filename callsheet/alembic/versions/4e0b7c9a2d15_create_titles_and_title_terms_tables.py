"""create titles and title_terms tables

Revision ID: 4e0b7c9a2d15
Revises: 3d9a2e5c8f41
Create Date: 2026-08-11 20:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4e0b7c9a2d15"
down_revision: str | None = "3d9a2e5c8f41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TITLE_TERM_TYPES = ("ALIAS", "HASHTAG", "CAST", "DIRECTOR", "MUSIC_DIRECTOR")


def upgrade() -> None:
    op.create_table(
        "titles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("poster_url", sa.String(length=2048), nullable=True),
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_titles_organization_id"), "titles", ["organization_id"])

    op.create_table(
        "title_terms",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title_id", sa.Uuid(), nullable=False),
        sa.Column(
            "term_type",
            sa.Enum(*TITLE_TERM_TYPES, name="title_term_type", native_enum=False),
            nullable=False,
        ),
        sa.Column("value", sa.String(length=300), nullable=False),
        sa.Column("normalized_value", sa.String(length=300), nullable=False),
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
            "title_id", "term_type", "normalized_value", name="uq_title_term_normalized"
        ),
    )
    op.create_index(op.f("ix_title_terms_title_id"), "title_terms", ["title_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_title_terms_title_id"), table_name="title_terms")
    op.drop_table("title_terms")
    op.drop_index(op.f("ix_titles_organization_id"), table_name="titles")
    op.drop_table("titles")
