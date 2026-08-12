"""link an artist entity to an account, and a title membership to its redeemer

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-12 12:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable, and stays null for every artist nobody has claimed — which is most of
    # them. `SET NULL` rather than `CASCADE`: deleting the account must not delete the
    # production house's record of who is on the film, only the claim over it.
    op.add_column("artists", sa.Column("linked_user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_artists_linked_user_id_users",
        "artists",
        "users",
        ["linked_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_artists_linked_user_id"), "artists", ["linked_user_id"])

    op.add_column("title_memberships", sa.Column("subject_user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_title_memberships_subject_user_id_users",
        "title_memberships",
        "users",
        ["subject_user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_title_memberships_subject_user_id"),
        "title_memberships",
        ["subject_user_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_title_memberships_subject_user_id"), table_name="title_memberships")
    op.drop_constraint(
        "fk_title_memberships_subject_user_id_users", "title_memberships", type_="foreignkey"
    )
    op.drop_column("title_memberships", "subject_user_id")

    op.drop_index(op.f("ix_artists_linked_user_id"), table_name="artists")
    op.drop_constraint("fk_artists_linked_user_id_users", "artists", type_="foreignkey")
    op.drop_column("artists", "linked_user_id")
