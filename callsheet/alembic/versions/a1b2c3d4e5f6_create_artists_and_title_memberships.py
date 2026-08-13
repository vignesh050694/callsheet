"""create artists, artist_identity_terms and title_memberships tables

Revision ID: a1b2c3d4e5f6
Revises: 9d5a2c7f0e83
Create Date: 2026-08-12 11:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "9d5a2c7f0e83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `SqlEnum(..., native_enum=False)` persists the member *name*, so these are the names,
# not the lowercase values the Python enums carry.
ARTIST_TERM_TYPES = ("NAME_VARIANT", "HANDLE")
TITLE_ROLES = ("TAGGED_ARTIST", "AGENCY_MANAGER")
TITLE_MEMBERSHIP_STATUSES = ("PENDING", "ACTIVE", "REVOKED")

_ARTIST_TERM_TYPE = sa.Enum(*ARTIST_TERM_TYPES, name="artist_term_type", native_enum=False)
_TITLE_ROLE = sa.Enum(*TITLE_ROLES, name="title_role", native_enum=False)
_TITLE_MEMBERSHIP_STATUS = sa.Enum(
    *TITLE_MEMBERSHIP_STATUSES, name="title_membership_status", native_enum=False
)


def upgrade() -> None:
    op.create_table(
        "artists",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
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
        sa.UniqueConstraint(
            "organization_id",
            "normalized_name",
            name="uq_artist_organization_normalized_name",
        ),
    )
    op.create_index(op.f("ix_artists_organization_id"), "artists", ["organization_id"])

    op.create_table(
        "artist_identity_terms",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("artist_id", sa.Uuid(), nullable=False),
        sa.Column("term_type", _ARTIST_TERM_TYPE, nullable=False),
        sa.Column("value", sa.String(length=300), nullable=False),
        sa.Column("normalized_value", sa.String(length=300), nullable=False),
        sa.Column("platform", sa.String(length=40), nullable=True),
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
        sa.ForeignKeyConstraint(["artist_id"], ["artists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "artist_id",
            "term_type",
            "normalized_value",
            name="uq_artist_term_normalized",
        ),
    )
    op.create_index(
        op.f("ix_artist_identity_terms_artist_id"), "artist_identity_terms", ["artist_id"]
    )

    op.create_table(
        "title_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title_id", sa.Uuid(), nullable=False),
        sa.Column("artist_id", sa.Uuid(), nullable=True),
        sa.Column("role", _TITLE_ROLE, nullable=False),
        sa.Column("status", _TITLE_MEMBERSHIP_STATUS, nullable=False),
        sa.Column("invited_email", sa.String(length=320), nullable=True),
        sa.Column("invited_handle", sa.String(length=300), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=True),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["artist_id"], ["artists.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("title_id", "artist_id", name="uq_title_membership_artist"),
        sa.CheckConstraint(
            "(role != 'TAGGED_ARTIST') OR (artist_id IS NOT NULL)",
            name="ck_title_membership_artist_subject",
        ),
        sa.CheckConstraint(
            "(invited_email IS NOT NULL) OR (invited_handle IS NOT NULL)",
            name="ck_title_membership_has_contact",
        ),
    )
    op.create_index(op.f("ix_title_memberships_title_id"), "title_memberships", ["title_id"])
    op.create_index(op.f("ix_title_memberships_artist_id"), "title_memberships", ["artist_id"])
    op.create_index(op.f("ix_title_memberships_status"), "title_memberships", ["status"])
    op.create_index(
        op.f("ix_title_memberships_token_hash"),
        "title_memberships",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("title_memberships")
    op.drop_table("artist_identity_terms")
    op.drop_table("artists")
