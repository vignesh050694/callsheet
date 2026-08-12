"""Reading stored timestamps back as instants.

Every datetime this application writes is UTC. What it reads back is not consistently
tagged: Postgres returns an aware value, SQLite returns a naive one holding the same
instant. Python treats those as unequal without complaint — `!=` between naive and aware
is silently `True`, unlike `<`, which at least raises — so any comparison between a stored
timestamp and a freshly computed one needs the two brought to the same footing first.

That defect has already been paid for once (E03-S04: a reprocess reported every mention as
changed on every run). It lives here rather than in the module that found it because the
rule is about *reading stored timestamps*, not about reprocessing, and the next caller to
need it should find it rather than rediscover the trap.

Only `reprocess_service` uses it today. The polling queue deliberately does not: `claim_due`
asks the database which cycles are due, so the comparison happens in SQL against a bound
parameter and never becomes a Python comparison between a stored value and a fresh one.
That is the better pattern where it is available, and this module is for where it is not.
"""

from datetime import UTC, datetime


def as_utc(value: datetime) -> datetime:
    """A naive value is stored UTC — that is the only thing this application writes."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def same_instant(left: datetime, right: datetime) -> bool:
    return as_utc(left) == as_utc(right)
