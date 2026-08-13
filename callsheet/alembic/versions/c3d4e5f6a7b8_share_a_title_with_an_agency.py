"""share a title with an agency organization, and audit every access change

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-12 14:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCESS_AUDIT_ACTIONS = ("GRANTED", "REVOKED")
TITLE_ROLES = ("TAGGED_ARTIST", "AGENCY_MANAGER")

_ACCESS_AUDIT_ACTION = sa.Enum(
    *ACCESS_AUDIT_ACTIONS, name="access_audit_action", native_enum=False
)
_TITLE_ROLE = sa.Enum(*TITLE_ROLES, name="title_role", native_enum=False)


def upgrade() -> None:
    op.add_column(
        "title_memberships", sa.Column("subject_organization_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_title_memberships_subject_organization_id_organizations",
        "title_memberships",
        "organizations",
        ["subject_organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_title_memberships_subject_organization_id"),
        "title_memberships",
        ["subject_organization_id"],
    )
    op.create_unique_constraint(
        "uq_title_membership_organization",
        "title_memberships",
        ["title_id", "subject_organization_id"],
    )
    op.create_check_constraint(
        "ck_title_membership_agency_subject",
        "title_memberships",
        "(role != 'AGENCY_MANAGER') OR (subject_organization_id IS NOT NULL)",
    )

    # An agency grant is not an invitation: nothing is sent, so there is no contact to
    # record and no send time. Both assumptions were baked in for tagged artists and have
    # to be narrowed to that role rather than dropped.
    op.drop_constraint("ck_title_membership_has_contact", "title_memberships", type_="check")
    op.create_check_constraint(
        "ck_title_membership_has_contact",
        "title_memberships",
        "(role != 'TAGGED_ARTIST') OR (invited_email IS NOT NULL) "
        "OR (invited_handle IS NOT NULL)",
    )
    op.alter_column(
        "title_memberships",
        "last_sent_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )

    op.create_table(
        "access_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title_id", sa.Uuid(), nullable=False),
        sa.Column("action", _ACCESS_AUDIT_ACTION, nullable=False),
        sa.Column("role", _TITLE_ROLE, nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        # No foreign keys on the subject columns on purpose: an audit row has to outlive
        # the organization or artist it refers to, which a cascade would delete.
        sa.Column("subject_organization_id", sa.Uuid(), nullable=True),
        sa.Column("subject_user_id", sa.Uuid(), nullable=True),
        sa.Column("subject_name", sa.String(length=300), nullable=False),
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
        # RESTRICT, not CASCADE: deleting the person who granted access must not erase the
        # record that they granted it.
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_access_audit_events_title_id"), "access_audit_events", ["title_id"]
    )
    op.create_index(
        op.f("ix_access_audit_events_actor_user_id"), "access_audit_events", ["actor_user_id"]
    )
    op.create_index(
        op.f("ix_access_audit_events_subject_organization_id"),
        "access_audit_events",
        ["subject_organization_id"],
    )
    op.create_index(
        op.f("ix_access_audit_events_subject_user_id"),
        "access_audit_events",
        ["subject_user_id"],
    )


def downgrade() -> None:
    op.drop_table("access_audit_events")

    # Agency grants are the thing this migration introduced, and both constraints below
    # are restored to shapes that no agency row can satisfy: it has no contact channel
    # and no `last_sent_at`, because nothing was ever sent to it. Removing the feature
    # removes its rows — without this, `alembic downgrade` fails with a NotNullViolation
    # the moment a single title has ever been shared, which is to say as soon as the
    # feature has been used at all.
    op.execute("DELETE FROM title_memberships WHERE role = 'AGENCY_MANAGER'")
    # Belt and braces for any row that predates the delete above or was written by hand:
    # the column is about to become NOT NULL, and `created_at` is the closest true value.
    op.execute(
        "UPDATE title_memberships SET last_sent_at = created_at WHERE last_sent_at IS NULL"
    )

    op.alter_column(
        "title_memberships",
        "last_sent_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.drop_constraint("ck_title_membership_has_contact", "title_memberships", type_="check")
    op.create_check_constraint(
        "ck_title_membership_has_contact",
        "title_memberships",
        "(invited_email IS NOT NULL) OR (invited_handle IS NOT NULL)",
    )
    op.drop_constraint("ck_title_membership_agency_subject", "title_memberships", type_="check")
    op.drop_constraint("uq_title_membership_organization", "title_memberships", type_="unique")
    op.drop_index(
        op.f("ix_title_memberships_subject_organization_id"), table_name="title_memberships"
    )
    op.drop_constraint(
        "fk_title_memberships_subject_organization_id_organizations",
        "title_memberships",
        type_="foreignkey",
    )
    op.drop_column("title_memberships", "subject_organization_id")
