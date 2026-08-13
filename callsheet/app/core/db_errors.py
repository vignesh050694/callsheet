"""Telling one `IntegrityError` apart from another.

SQLAlchemy raises the same exception class for every constraint the database refuses, so a
service that catches `IntegrityError` and reports "duplicate" is guessing. When the guess is
wrong the caller is told the opposite of what happened: a missing column default surfaced as
"this title already contains that campaign milestone", which sent a real investigation
looking for a duplicate row that was never there.

A uniqueness violation is the only integrity failure a service can honestly translate into a
409, because it is the only one that means "what you sent collides with what is stored".
Everything else — a not-null violation, a broken foreign key, a failed check — is the schema
disagreeing with the code, and that is a 500 with a traceback, not a message to the user.
"""

from sqlalchemy.exc import IntegrityError

# Postgres SQLSTATE for unique_violation. asyncpg exposes it as `sqlstate`, psycopg as
# `pgcode`; both are checked so the helper does not depend on which driver is bound.
UNIQUE_VIOLATION_SQLSTATE = "23505"

# SQLite has no SQLSTATE. The test suite runs on it, so the message is the only signal
# available there — matched lowercased against "UNIQUE constraint failed: <table>.<column>".
_SQLITE_UNIQUE_MARKER = "unique constraint failed"


def is_unique_violation(error: IntegrityError) -> bool:
    """Whether this integrity failure is a uniqueness collision rather than anything else."""
    original = error.orig
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    if sqlstate is not None:
        return bool(sqlstate == UNIQUE_VIOLATION_SQLSTATE)
    return _SQLITE_UNIQUE_MARKER in str(original).lower()
