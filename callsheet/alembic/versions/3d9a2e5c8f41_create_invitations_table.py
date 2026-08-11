"""create invitations table

Adds the `viewer` membership role alongside it. `membership_role` is a non-native enum
(a VARCHAR plus a CHECK constraint), so widening it is a column alter rather than a
Postgres ENUM migration.

Revision ID: 3d9a2e5c8f41
Revises: 2c8f1d4a7b30
Create Date: 2026-08-11 19:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3d9a2e5c8f41"
down_revision: str | None = "2c8f1d4a7b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_MEMBERSHIP_ROLES = ("OWNER",)
NEW_MEMBERSHIP_ROLES = ("OWNER", "VIEWER")


def upgrade() -> None:
    with op.batch_alter_table("memberships") as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=sa.Enum(*OLD_MEMBERSHIP_ROLES, name="membership_role", native_enum=False),
            type_=sa.Enum(*NEW_MEMBERSHIP_ROLES, name="membership_role", native_enum=False),
            existing_nullable=False,
        )

    op.create_table(
        "invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "role",
            sa.Enum(*NEW_MEMBERSHIP_ROLES, name="membership_role", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("PENDING", "ACCEPTED", "CANCELLED", name="invitation_status",
                    native_enum=False),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_invitations_organization_id"), "invitations", ["organization_id"]
    )
    op.create_index(op.f("ix_invitations_status"), "invitations", ["status"])
    op.create_index(op.f("ix_invitations_token_hash"), "invitations", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_invitations_token_hash"), table_name="invitations")
    op.drop_index(op.f("ix_invitations_status"), table_name="invitations")
    op.drop_index(op.f("ix_invitations_organization_id"), table_name="invitations")
    op.drop_table("invitations")

    with op.batch_alter_table("memberships") as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=sa.Enum(*NEW_MEMBERSHIP_ROLES, name="membership_role", native_enum=False),
            type_=sa.Enum(*OLD_MEMBERSHIP_ROLES, name="membership_role", native_enum=False),
            existing_nullable=False,
        )
