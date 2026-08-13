"""restore title milestone timestamp defaults

Revision ID: c07e5a9b2f14
Revises: bf7c4e2a5d13
Create Date: 2026-08-13

Repairs schema drift on `title_milestones` (found testing E02-S02).

`created_at` and `updated_at` are `NOT NULL` and carry no Python-side default: `TimestampMixin`
declares `server_default=func.now()` and the ORM leaves both columns out of the INSERT entirely,
expecting the database to fill them. On a database where that default is missing, every insert
of a campaign milestone fails with a not-null violation — which is to say campaign milestones
could not be saved at all, on any code path, while identity terms on the same request saved
fine.

The table's own creation migration (`5f1c8d3b6e29`) does declare both defaults, so a database
built from a clean migration run was never affected. The drift belongs to databases migrated
before that file reached its committed form; they are now at head with a table that no
migration in the chain describes, which is exactly the state nothing else would ever correct.

`SET DEFAULT` is idempotent and unconditional here on purpose. Making it conditional on the
current default would leave the two kinds of database in different states with no way to tell
them apart later, and re-asserting a default that is already correct costs nothing.

Not reversed in `downgrade`: dropping these defaults would restore a schema that cannot accept
an insert the application makes, and a downgrade that reinstates a defect is not a downgrade.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c07e5a9b2f14"
down_revision: str | Sequence[str] | None = "bf7c4e2a5d13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TIMESTAMP_COLUMNS = ("created_at", "updated_at")


def upgrade() -> None:
    for column in _TIMESTAMP_COLUMNS:
        op.execute(f"ALTER TABLE title_milestones ALTER COLUMN {column} SET DEFAULT now()")


def downgrade() -> None:
    # Deliberately empty — see the module docstring.
    pass
