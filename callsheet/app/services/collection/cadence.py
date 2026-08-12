"""How often a title is polled (E03-S01), and the one place E03-S02 will replace.

This story runs every title at a single rate. E03-S02 makes that rate depend on where the
title is in its campaign — dormant 2/day, campaign 12/day, release surge 48/day — and the
story is explicit that this one must not put the rate anywhere S02 cannot reach.

Hence a policy object rather than a constant. Everything that needs to know when the next
poll is due asks a `CadencePolicy`; nothing multiplies hours by anything itself. Swapping
in a phase-aware policy is then a binding change in `deps.py`, not a search for arithmetic
scattered across a scheduler.

The rate is deliberately expressed as **polls per day** rather than as an interval, because
that is the unit the cost model is written in (concept note §7: ~$0.225 per poll,
~$273 per title) and the unit E09's projection will read. An interval is derived from it;
the reverse conversion is where a rounding error becomes a billing surprise.
"""

import abc
from datetime import datetime, timedelta

import structlog

from app.core.config import MAX_POLLS_PER_DAY, MIN_POLLS_PER_DAY
from app.models.title import Title

_logger = structlog.get_logger(__name__)

HOURS_PER_DAY = 24


class CadencePolicy(abc.ABC):
    """Decides a title's polling rate, and derives the schedule from it."""

    @abc.abstractmethod
    def polls_per_day(self, title: Title) -> int:
        """How many times a day this title should be collected, right now."""

    def interval(self, title: Title) -> timedelta:
        """The gap between consecutive polls at this title's current rate."""
        rate = self._validated_rate(title)
        return timedelta(hours=HOURS_PER_DAY / rate)

    def next_run_at(self, title: Title, *, after: datetime) -> datetime:
        """When the cycle following `after` becomes due.

        Measured from when the previous cycle *finished*, not from when it was due. A run
        that was late — a worker was down, a provider was slow — would otherwise have its
        successor fall due immediately, and a backlog of overdue cycles would then run
        back to back at full cost with no gap between them. Drift is the cheaper error.
        """
        return after + self.interval(title)

    def _validated_rate(self, title: Title) -> int:
        """The same bound configuration is checked against, enforced again at use.

        Configuration is not the only source of a rate — E03-S02 computes one per title
        from its campaign phase — so the policy re-checks rather than assuming whatever
        produced the number already did.
        """
        rate = self.polls_per_day(title)
        if rate < MIN_POLLS_PER_DAY or rate > MAX_POLLS_PER_DAY:
            _logger.error(
                "collection.cadence.rate_out_of_range",
                title_id=str(title.id),
                polls_per_day=rate,
                maximum=MAX_POLLS_PER_DAY,
            )
            raise ValueError(
                f"A polling rate of {rate} per day is outside the supported range "
                f"{MIN_POLLS_PER_DAY}-{MAX_POLLS_PER_DAY}"
            )
        return rate


class FixedCadencePolicy(CadencePolicy):
    """One rate for every title, whatever phase it is in.

    The rate this story ships at is the concept note's **campaign** rate, not its dormant
    one. A single rate has to be wrong somewhere, and the two directions are not
    symmetrical: too slow means a studio watching an opening weekend sees numbers hours
    old, which is the failure the product is bought to avoid. Too fast costs money on quiet
    months, which is real but recoverable — and it is exactly what E03-S02 exists to fix.
    """

    def __init__(self, polls_per_day: int) -> None:
        self._polls_per_day = polls_per_day

    def polls_per_day(self, title: Title) -> int:
        return self._polls_per_day
