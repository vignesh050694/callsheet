"""Turning a database uniqueness violation into something a studio can act on.

A unique constraint is the only place some rules are really enforced — two processes
racing past an in-memory check both lose to the index, which is the point of having one.
But the error that comes back names a constraint, and the message built from it used to
name *every* rule the table could have broken: "this title already contains that identity
term or campaign milestone" came back whichever of the two it was, on a screen carrying a
dozen term fields and a milestone list. A studio reading that has to guess which of
fourteen inputs to change, and the two candidates are not even in the same section.

So the constraint is read and answered specifically. The generic message survives as the
fallback, because an unmapped constraint must still produce a 409 the caller can act on
rather than a 500 — but the log line always carries what was matched, so the fallback
firing is something a person can find rather than a mystery.

**Postgres and SQLite report this differently, and both have to work.** asyncpg puts the
constraint's name on the exception; SQLite names only the table and columns, never the
constraint. The suite runs on SQLite and production runs on Postgres, so a diagnosis that
worked on one of them would be worth very little — it would be absent from exactly the
environment where the bug is being reported. Each rule therefore carries both handles.
"""

from dataclasses import dataclass

import structlog
from sqlalchemy.exc import IntegrityError

_logger = structlog.get_logger(__name__)

DUPLICATE_ENTRY_MESSAGE = "This title already contains that identity term or campaign milestone"


@dataclass(frozen=True, slots=True)
class _UniqueRule:
    """One uniqueness rule, in the two forms the two drivers describe it by."""

    constraint: str
    table: str
    message: str


_RULES: tuple[_UniqueRule, ...] = (
    _UniqueRule(
        constraint="uq_title_term_normalized",
        table="title_terms",
        message=(
            "This title already lists that identity term. Each alias, hashtag, cast "
            "member, director and exclusion can appear only once."
        ),
    ),
    _UniqueRule(
        constraint="uq_title_milestone_name_date",
        table="title_milestones",
        message=(
            "This title already has a campaign milestone with that name on that date. "
            "Two beats can share a name if they fall on different days."
        ),
    ),
    _UniqueRule(
        constraint="uq_collection_run_one_pending_per_title",
        table="collection_runs",
        message="A collection cycle is already queued for this title, so another was not added.",
    ),
)


def describe_integrity_error(error: IntegrityError, **log_context: object) -> str:
    """The message for whichever rule this violation broke, plus a log line naming it.

    Always logs, and always says what it matched — or that it matched nothing. An
    unmapped constraint reaching a studio as the generic wording is a small failure;
    it reaching them with nothing in the log to say which rule fired is the failure
    that costs somebody an afternoon.
    """
    rule = _match_rule(error)

    _logger.warning(
        "db.integrity_violation",
        rule=rule.constraint if rule else "unmapped",
        # The driver's own text, bounded. When nothing matched, this is the only thing
        # that helps, so it is logged whether or not the match succeeded.
        detail=str(error.orig)[:300],
        **log_context,
    )
    return rule.message if rule else DUPLICATE_ENTRY_MESSAGE


def _match_rule(error: IntegrityError) -> _UniqueRule | None:
    """By constraint name where the driver gives one, by table name where it does not.

    **A named constraint that is not one of ours matches nothing**, rather than falling
    through to the table-name search. `IntegrityError` covers foreign keys, check
    constraints and not-null violations too, and every one of those also names a table.
    Falling through would answer a foreign-key violation on `title_terms` — a genuine
    integrity bug — with "this title already lists that identity term", telling the studio
    to edit a field that is fine and telling whoever reads the log to go and look at the
    wrong constraint.

    The table fallback exists only for SQLite, which names columns and never constraints,
    so it is gated on the text actually describing a *uniqueness* failure.
    """
    named = getattr(error.orig, "constraint_name", None)
    if isinstance(named, str) and named:
        return next((rule for rule in _RULES if rule.constraint == named), None)

    text = str(error.orig)
    for rule in _RULES:
        if rule.constraint in text:
            return rule

    if not _is_unique_violation(text):
        return None
    return next((rule for rule in _RULES if rule.table in text), None)


def _is_unique_violation(text: str) -> bool:
    """Whether a driver's message describes a uniqueness failure rather than some other one.

    SQLite says `UNIQUE constraint failed: title_terms.title_id, ...`; psycopg's text form
    says `duplicate key value violates unique constraint`. Both are matched loosely, and a
    message matching neither is left unattributed — the generic 409 is the honest answer
    when the only thing known is "some constraint, on some table".
    """
    lowered = text.lower()
    return "unique" in lowered or "duplicate key" in lowered
