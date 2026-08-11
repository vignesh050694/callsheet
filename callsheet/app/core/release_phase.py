"""The pre-release / post-release boundary (E02-S02).

The split is a **read-time** property, not a stored one. Nothing is stamped with a phase
when it is collected: a mention carries its timestamp, the title carries its release date,
and the phase is derived from the two whenever something asks. That is what lets a studio
correct a release date after collection has started and see every chart re-split without
re-collecting or re-analysing anything.

Every consumer must derive the phase here rather than comparing dates itself, or a date
pushed by a week splits one chart and not the next.

`callsheet-ui/src/lib/release-phase.ts` mirrors this. The two have to move together.
"""

import enum
from datetime import UTC, date, datetime


class ReleasePhase(enum.StrEnum):
    PRE_RELEASE = "pre_release"
    POST_RELEASE = "post_release"


def phase_for_date(day: date, release_date: date) -> ReleasePhase:
    """Release day itself counts as post-release.

    The release is the event, not the boundary before it — first-day-first-show reaction
    is the loudest post-release signal there is, and putting it on the pre-release side of
    the divider would make opening-day volume read as anticipation.
    """
    if day >= release_date:
        return ReleasePhase.POST_RELEASE
    return ReleasePhase.PRE_RELEASE


def phase_for(occurred_at: datetime, release_date: date) -> ReleasePhase:
    """Which side of the release a moment falls on.

    Compared in UTC, because that is what is stored. A release date is a calendar day
    rather than an instant, so a post made in IST late on release eve lands pre-release
    when its UTC date is still the day before — a deliberate simplification that holds
    until territory-specific dates arrive (explicitly out of scope for this story).
    """
    return phase_for_date(_utc_date_of(occurred_at), release_date)


def _utc_date_of(moment: datetime) -> date:
    """A naive datetime is read as UTC — every timestamp this system stores already is."""
    if moment.tzinfo is None:
        return moment.date()
    return moment.astimezone(UTC).date()
