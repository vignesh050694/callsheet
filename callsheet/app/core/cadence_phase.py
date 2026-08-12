"""Where a title sits in its campaign, and therefore how hard it is polled (E03-S02).

Three phases, from the concept note's §7 cost model: **dormant** (2 polls a day),
**campaign** (12), **release surge** (48). The rates are the product's single largest cost
lever — collection is ~$0.225 a poll, so the difference between polling a quiet month at
surge rate and at dormant rate is the difference between a title costing $273 and $1,200.

This module owns the **calendar** half of the decision and nothing else: given a day and a
release date, which phase is that day in. It holds no rates, reads no database, and knows
nothing about observed volume — that half lives in `services/collection/cadence.py`, which
can escalate what this returns. Keeping them apart is what lets the window boundaries be
tested as pure arithmetic against the cost model they were derived from.

**The windows are derived, not chosen.** The concept note fixes the three rates and the
~$273 total for a six-month campaign; it does not say how long each phase lasts. Working
backwards from those two facts over a tracking window running 152 days before release to 30
days after (183 days, the note's "six-month campaign"):

    dormant   124 days x  2 =  248 polls
    campaign   52 days x 12 =  624 polls
    surge       7 days x 48 =  336 polls
                              ----------
                              1208 polls x $0.225 = $271.80

which is the note's figure. `cadence_cost.py` computes exactly this, so a change to a
window here moves a number E09-S04 reads rather than quietly invalidating the epic's gate.

`callsheet-ui/src/lib/cadence-phase.ts` mirrors the labels. The two have to move together.
"""

import enum
from datetime import date, timedelta

# Release week, as a film distributor means it: the Friday opening and the weekend that
# decides the title, plus the two days of anticipation that precede it. Asymmetric on
# purpose — first-day-first-show reaction is the loudest signal a title ever produces, and
# it lands after the release, not before.
SURGE_DAYS_BEFORE_RELEASE = 2
SURGE_DAYS_AFTER_RELEASE = 4

# The active campaign around the surge: promotion is running, trailers and songs are out,
# and there is a conversation worth sampling every couple of hours. It extends further
# after the release than the surge does because word of mouth outlives the opening weekend.
CAMPAIGN_DAYS_BEFORE_RELEASE = 30
CAMPAIGN_DAYS_AFTER_RELEASE = 28


class CadencePhase(enum.StrEnum):
    """How hard a title is being polled, and why.

    Ordered dormant → campaign → surge. `escalated` walks that order, which is what a
    volume spike does to a title the calendar considers quiet.
    """

    DORMANT = "dormant"
    CAMPAIGN = "campaign"
    RELEASE_SURGE = "release_surge"

    @property
    def rank(self) -> int:
        return _PHASE_ORDER.index(self)

    @property
    def escalated(self) -> "CadencePhase":
        """One step up the order, and no further."""
        next_rank = min(self.rank + 1, len(_PHASE_ORDER) - 1)
        return _PHASE_ORDER[next_rank]

    @property
    def is_volume_escalatable(self) -> bool:
        """Whether a volume spike is allowed to raise this phase at all.

        True for dormant and nothing else, and that is the whole rule: a spike can lift a
        quiet title to campaign rates, and it can never buy surge rates.

        **Surge is the calendar's to grant.** Escalation is a heuristic over observed
        volume, and the gap between campaign and surge is 12/day to 48/day — a heuristic
        that can quadruple a bill on its own judgement is one nobody will leave switched
        on. Campaign is also the widest window this product has, and ordinary campaign
        events (a trailer drop, a song release) routinely clear a 3x-baseline spike, so a
        campaign title allowed to escalate would spend weeks at release-week rates without
        release week ever arriving — against a cost model (`cadence_cost.py`) that budgets
        surge for seven days.

        Derived from the ceiling below rather than written as a second condition, so this
        rule and the number it is stated in cannot drift apart.
        """
        return self.escalated.rank <= HIGHEST_VOLUME_ESCALATED_PHASE.rank


_PHASE_ORDER: tuple[CadencePhase, ...] = (
    CadencePhase.DORMANT,
    CadencePhase.CAMPAIGN,
    CadencePhase.RELEASE_SURGE,
)

# The highest rate observed volume may buy on its own. The story asks for a controversy in
# the *dormant* phase to escalate cadence and asks for nothing above that.
HIGHEST_VOLUME_ESCALATED_PHASE = CadencePhase.CAMPAIGN


def phase_for_day(day: date, release_date: date) -> CadencePhase:
    """The phase a calendar day falls in, before any volume signal is considered.

    Boundaries are **inclusive on both sides**, so a title whose release is exactly two
    days away is already surging. The alternative — surging from the day after the boundary
    — means the escalation the studio is watching for arrives a day into the window it was
    meant to cover.
    """
    if _is_within(day, release_date, SURGE_DAYS_BEFORE_RELEASE, SURGE_DAYS_AFTER_RELEASE):
        return CadencePhase.RELEASE_SURGE
    if _is_within(day, release_date, CAMPAIGN_DAYS_BEFORE_RELEASE, CAMPAIGN_DAYS_AFTER_RELEASE):
        return CadencePhase.CAMPAIGN
    return CadencePhase.DORMANT


def _is_within(day: date, release_date: date, days_before: int, days_after: int) -> bool:
    return (
        release_date - timedelta(days=days_before)
        <= day
        <= release_date + timedelta(days=days_after)
    )
