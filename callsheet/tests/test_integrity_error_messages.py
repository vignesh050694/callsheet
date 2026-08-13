"""Which rule a 409 blames, and — just as importantly — which ones it refuses to blame.

`TitleService` funnels three unrelated uniqueness rules through one `except IntegrityError`
handler: identity terms, campaign milestones, and the first collection run. It used to
answer all three with one sentence naming two of them, on a screen carrying a dozen term
fields and a milestone list, so a studio hitting it had to guess which of fourteen inputs
to change.

The half that is easy to get wrong is the *negative* case. `IntegrityError` also covers
foreign keys, check constraints and not-null violations, and every one of those names a
table too. Attributing those to a uniqueness rule tells the studio to edit a field that is
fine and points whoever reads the log at the wrong constraint — a genuine integrity bug
wearing the costume of ordinary user error.

Both drivers are exercised because they describe the same failure differently and both are
real here: SQLite runs the suite and names columns, Postgres runs production and names the
constraint. A diagnosis that only worked on one would be missing from exactly the
environment where the bug gets reported.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.constraints import DUPLICATE_ENTRY_MESSAGE, describe_integrity_error


class _DriverError(Exception):
    """Stands in for asyncpg's or SQLite's own exception under `IntegrityError.orig`.

    asyncpg exposes `constraint_name`; SQLite has no such attribute, which is exactly the
    difference the matcher has to absorb, so it is modelled rather than assumed.
    """

    def __init__(self, text: str, constraint_name: str | None = None) -> None:
        super().__init__(text)
        if constraint_name is not None:
            self.constraint_name = constraint_name


def _describe(text: str, constraint_name: str | None = None) -> str:
    return describe_integrity_error(IntegrityError("stmt", {}, _DriverError(text, constraint_name)))


# ---------------------------------------------------------------------------
# Postgres — the driver names the constraint, so the match is exact.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("constraint", "expected_fragment"),
    [
        ("uq_title_term_normalized", "already lists that identity term"),
        ("uq_title_milestone_name_date", "campaign milestone with that name on that date"),
        ("uq_collection_run_one_pending_per_title", "collection cycle is already queued"),
    ],
)
def test_named_constraint_is_answered_with_its_own_rule(
    constraint: str, expected_fragment: str
) -> None:
    message = _describe("duplicate key value violates unique constraint", constraint)

    assert expected_fragment in message
    assert message != DUPLICATE_ENTRY_MESSAGE


# ---------------------------------------------------------------------------
# SQLite — no constraint name anywhere, only the table and columns.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected_fragment"),
    [
        (
            "UNIQUE constraint failed: title_terms.title_id, title_terms.normalized_value",
            "already lists that identity term",
        ),
        (
            "UNIQUE constraint failed: title_milestones.title_id, title_milestones.occurs_on",
            "campaign milestone with that name on that date",
        ),
        (
            "UNIQUE constraint failed: collection_runs.title_id",
            "collection cycle is already queued",
        ),
    ],
)
def test_sqlite_is_attributed_by_table_when_no_constraint_is_named(
    text: str, expected_fragment: str
) -> None:
    assert expected_fragment in _describe(text)


# ---------------------------------------------------------------------------
# The negative cases — the ones that make the positive ones trustworthy.
# ---------------------------------------------------------------------------


def test_a_foreign_key_violation_naming_a_known_table_is_not_blamed_on_that_tables_rule() -> None:
    """The regression this file mainly exists for.

    A foreign-key failure on `title_terms` — a real integrity bug, e.g. a parent title
    deleted mid-transaction — must not come back as "this title already lists that
    identity term". That would send the studio editing a field that is correct and send
    an engineer reading the log to a constraint that never fired.
    """
    message = _describe(
        'insert or update on table "title_terms" violates foreign key constraint '
        '"title_terms_title_id_fkey"',
        "title_terms_title_id_fkey",
    )

    assert message == DUPLICATE_ENTRY_MESSAGE


def test_a_foreign_key_violation_with_no_constraint_name_is_also_not_blamed() -> None:
    """Same failure as above through a driver that names no constraint.

    The table fallback is the part that has to say no here: the text mentions
    `title_terms`, and only "this is not a uniqueness failure" keeps it from matching.
    """
    message = _describe(
        'insert or update on table "title_terms" violates foreign key constraint'
    )

    assert message == DUPLICATE_ENTRY_MESSAGE


def test_an_unmapped_unique_constraint_falls_back_rather_than_guessing() -> None:
    """A 409 the caller can act on beats a 500, even when the rule is unrecognised."""
    assert _describe("UNIQUE constraint failed: organizations.slug") == DUPLICATE_ENTRY_MESSAGE
