"""What a cadence policy costs over a campaign (E03-S02, read by E09-S04).

The story is explicit that cadence is the primary lever on the ~$273-per-title model and
that any change to the policy has to be reflected in the cost projection. This module is
how that is kept true by construction rather than by remembering: the projection walks the
*same* `phase_for_day` the scheduler polls by, so moving a window boundary moves this
number in the same commit.

It is pure arithmetic over a calendar. No database, no route, no screen — E09-S04 owns what
is *shown*; this owns what is *counted*, so that story reads a figure rather than deriving a
second one that can disagree with the scheduler.

Volume escalation is deliberately not modelled. It is a response to something unplanned, and
a projection that budgeted for the average controversy would be a projection of a title that
does not exist. The honest form is "this is what the calendar costs"; an escalation is then
visible as an overrun, which is exactly what E09 needs to alert on.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from app.core.cadence_phase import CadencePhase, phase_for_day
from app.services.collection.cadence import CadenceRates


@dataclass(frozen=True, slots=True)
class CadenceCostProjection:
    """Polls and spend over a window, and the phase breakdown behind them."""

    days_by_phase: dict[CadencePhase, int]
    polls_by_phase: dict[CadencePhase, int]
    cost_per_poll_usd: float

    @property
    def total_days(self) -> int:
        return sum(self.days_by_phase.values())

    @property
    def total_polls(self) -> int:
        return sum(self.polls_by_phase.values())

    @property
    def total_cost_usd(self) -> float:
        return self.total_polls * self.cost_per_poll_usd

    def cost_usd_for_phase(self, phase: CadencePhase) -> float:
        return self.polls_by_phase.get(phase, 0) * self.cost_per_poll_usd


def project_campaign_cost(
    *,
    release_date: date,
    tracked_from: date,
    tracked_until: date,
    rates: CadenceRates,
    cost_per_poll_usd: float,
) -> CadenceCostProjection:
    """What tracking one title from `tracked_from` to `tracked_until` costs to collect.

    Both bounds inclusive — a studio asked to name a tracking window names two days it wants
    covered, not a half-open interval.

    Counts whole days at each day's own phase. That is a simplification of a schedule that
    changes mid-day when a boundary is crossed, and it is worth at most a few polls over a
    six-month window against a figure quoted to the dollar.
    """
    if tracked_until < tracked_from:
        raise ValueError("A tracking window cannot end before it begins")

    days_by_phase: dict[CadencePhase, int] = {phase: 0 for phase in CadencePhase}
    day = tracked_from
    while day <= tracked_until:
        days_by_phase[phase_for_day(day, release_date)] += 1
        day += timedelta(days=1)

    return CadenceCostProjection(
        days_by_phase=days_by_phase,
        polls_by_phase={
            phase: days * rates.for_phase(phase) for phase, days in days_by_phase.items()
        },
        cost_per_poll_usd=cost_per_poll_usd,
    )
