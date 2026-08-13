"""When a platform counts as stale, and what that does to a freshness claim (E03-S05).

Pure arithmetic over an interval and two instants — no database, no route, no screen — for
the same reason `cadence_cost` is: the rule has to be one fact that the dashboard, the
alerting threshold and the tests all read, rather than three implementations that agree
until one of them is edited.

**Staleness is measured against the title's current cadence phase**, which is what makes it
meaningful. A dormant title polls twice a day, so eight hours of silence is a title behaving
normally; a title in release surge polls every half hour, and eight hours of silence there is
an outage that has been running most of an opening weekend. One absolute threshold would
either scream through every quiet campaign or stay silent through exactly the window the
story is written about.

**The tolerance is more than one interval, deliberately.** After one interval a poll is
merely *due* — the worker ticks on its own schedule and a cycle that lands a minute late is
not a coverage gap. After two, a poll that should have happened has not. Anything tighter
turns the dashboard into a flapping light that people learn to ignore, which is worse than
no light at all, because this indicator only earns its place if being lit is believed.
"""

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta


class PlatformHealthState(enum.StrEnum):
    """What a platform's collection is doing, as a screen has to render it."""

    # Succeeded recently enough for its current cadence. The only state that counts as the
    # platform reporting, and the only one included in an "as of" claim.
    REPORTING = "reporting"
    # Has succeeded before, but not recently enough — or has been tried and has never
    # succeeded at all. Both are "this platform is not currently reporting", which is the
    # sentence the story asks the dashboard to say.
    STALE = "stale"
    # Configured, and not yet attempted. Distinct from stale because nothing is wrong: a
    # title created a minute ago has not had its first cycle. Calling this stale would greet
    # every new title with a warning, which is the fastest way to teach people to ignore it.
    PENDING = "pending"

    @property
    def is_reporting(self) -> bool:
        return self is PlatformHealthState.REPORTING

    @property
    def is_stale(self) -> bool:
        return self is PlatformHealthState.STALE


@dataclass(frozen=True, slots=True)
class PlatformHealth:
    """One platform's collection health for one title."""

    platform: str
    state: PlatformHealthState
    last_successful_at: datetime | None
    last_failure_reason: str | None
    consecutive_failures: int

    @property
    def is_stale(self) -> bool:
        return self.state.is_stale


def staleness_deadline(
    last_successful_at: datetime, *, interval: timedelta, tolerance: float
) -> datetime:
    """The instant after which a platform that last succeeded then counts as stale."""
    return last_successful_at + interval * tolerance


def health_state_for(
    *,
    last_successful_at: datetime | None,
    has_been_attempted: bool,
    interval: timedelta,
    tolerance: float,
    now: datetime,
) -> PlatformHealthState:
    """Whether this platform is reporting, stale, or has not started yet.

    The never-succeeded case splits on whether anything has been *tried*, and that split is
    the whole of the difference between a new title and a broken one. Never tried is
    `PENDING` — the first cycle has not run. Tried and never succeeded is `STALE`, however
    recently it was tried: a platform that has been asked and has never once answered is
    precisely the "not currently reporting" the story wants said out loud, and waiting for
    an interval to elapse before saying so would mean the first thing a studio sees about a
    misconfigured platform is silence.
    """
    if last_successful_at is None:
        return PlatformHealthState.STALE if has_been_attempted else PlatformHealthState.PENDING
    deadline = staleness_deadline(last_successful_at, interval=interval, tolerance=tolerance)
    return PlatformHealthState.STALE if now > deadline else PlatformHealthState.REPORTING


def freshness_as_of(healths: list[PlatformHealth]) -> datetime | None:
    """The instant a dashboard may honestly claim its data is current to.

    **The oldest success among the platforms that are still reporting**, and each half of
    that is load-bearing.

    *Oldest* rather than newest, because an "as of" is a claim about everything on the
    screen. Quoting the most recent success would let one platform that polled a minute ago
    speak for three that last polled an hour ago, which is the flattering answer and the
    wrong one.

    *Reporting only*, because the story says so and because the alternative is useless in
    both directions. Including a stale platform would drag the claim back to whenever
    Instagram last worked — possibly days — and describe three healthy platforms as days
    stale; excluding it silently would let the screen claim freshness it does not have for
    Instagram's share of the data. The resolution is this function plus the warning that
    travels with it: the claim covers what is reporting, and what is not reporting is named.

    `None` when nothing is reporting, which a caller must render as "no current data" rather
    than as a timestamp it has quietly invented.
    """
    successes = [
        health.last_successful_at
        for health in healths
        if health.state.is_reporting and health.last_successful_at is not None
    ]
    return min(successes) if successes else None
