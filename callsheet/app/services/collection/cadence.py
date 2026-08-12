"""How often a title is polled, and why it is that often (E03-S02).

E03-S01 shipped one rate for every title and put it behind this policy so that exactly one
thing would need replacing. This is that replacement. A title's rate now comes from where it
is in its campaign — dormant 2/day, campaign 12/day, release surge 48/day — with the
calendar deciding the ordinary case and observed volume able to escalate it.

Two inputs, deliberately kept separate:

* **The calendar** (`core/cadence_phase.py`) is the authority. It is predictable, it is what
  the ~$273 cost model is built on, and a studio can plan around it.
* **Observed volume** can only ever push a title *up*, and only one step. A controversy in a
  dormant month is the case the story names — a title nobody expected to be talking about
  suddenly is, eight months before release, and waiting twelve hours for the next scheduled
  poll is how a studio finds out about it from somebody else.

The rate is expressed as **polls per day** rather than as an interval, because that is the
unit the cost model is written in (concept note §7: ~$0.225 per poll, ~$273 per title) and
the unit E09's projection reads. An interval is derived from it; the reverse conversion is
where a rounding error becomes a billing surprise.

Nothing outside this module multiplies a rate by anything. A `CadenceDecision` carries both
the rate and the schedule it implies, so a caller cannot stamp one number on a run and
schedule it by another.
"""

import abc
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import structlog

from app.core.cadence_phase import CadencePhase, phase_for_day
from app.core.config import MAX_POLLS_PER_DAY, MIN_POLLS_PER_DAY, Settings
from app.models.title import Title

_logger = structlog.get_logger(__name__)

HOURS_PER_DAY = 24


@dataclass(frozen=True, slots=True)
class CadenceRates:
    """Polls per day for each phase — the three numbers the cost model is built on."""

    dormant: int
    campaign: int
    release_surge: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "CadenceRates":
        return cls(
            dormant=settings.collection_dormant_polls_per_day,
            campaign=settings.collection_campaign_polls_per_day,
            release_surge=settings.collection_surge_polls_per_day,
        )

    def for_phase(self, phase: CadencePhase) -> int:
        if phase is CadencePhase.RELEASE_SURGE:
            return self.release_surge
        if phase is CadencePhase.CAMPAIGN:
            return self.campaign
        return self.dormant


@dataclass(frozen=True, slots=True)
class VolumeReading:
    """What a title's recent mention volume looks like against its own history.

    Measured on `posted_at`, not on when a mention was collected. A backfill (E03-S03) drops
    thousands of rows into the corpus at once, and every one of them is months old — reading
    collection time would make importing history look identical to a controversy.
    """

    recent_count: int
    baseline_daily_mean: float


@dataclass(frozen=True, slots=True)
class VolumeEscalationRule:
    """When a title is busy enough to poll harder than its calendar says.

    Two conditions, and both are needed. The multiplier alone would escalate a title that
    went from one mention a day to four, which is noise wearing the shape of a spike. The
    floor alone would escalate any title with a normal campaign volume, permanently.
    """

    spike_multiplier: float
    minimum_mentions: int
    baseline_days: int
    recent_hours: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "VolumeEscalationRule":
        return cls(
            spike_multiplier=settings.collection_volume_spike_multiplier,
            minimum_mentions=settings.collection_volume_spike_minimum_mentions,
            baseline_days=settings.collection_volume_baseline_days,
            recent_hours=settings.collection_volume_recent_hours,
        )

    def is_spike(self, reading: VolumeReading) -> bool:
        """A title with no history at all spikes on the floor alone.

        `baseline_daily_mean` of zero is the story's case, not an edge case: a dormant title
        eight months from release has no mentions to compare against, so anything above the
        floor is by definition unlike anything it has done before.
        """
        if reading.recent_count < self.minimum_mentions:
            return False
        return reading.recent_count >= reading.baseline_daily_mean * self.spike_multiplier


class TitleVolumeReader(abc.ABC):
    """Reads a title's recent volume against its own baseline.

    A port rather than a repository call inside the policy, so the phase arithmetic can be
    tested without a database and so a policy with no volume input at all is expressible.
    """

    @abc.abstractmethod
    async def read(
        self, title_id: uuid.UUID, *, now: datetime, rule: VolumeEscalationRule
    ) -> VolumeReading:
        """This title's mentions in the recent window, and its daily mean before it."""


@dataclass(frozen=True, slots=True)
class CadenceDecision:
    """A rate, the phase that produced it, and the schedule it implies.

    Validated on construction, so a policy cannot hand out a rate that does not describe a
    schedule. The same bound configuration is checked against is enforced again here,
    because configuration is no longer the only source of a rate — a phase lookup produces
    one too, and a policy written later will produce it some third way.
    """

    phase: CadencePhase
    calendar_phase: CadencePhase
    polls_per_day: int
    is_volume_escalated: bool

    def __post_init__(self) -> None:
        if self.polls_per_day < MIN_POLLS_PER_DAY or self.polls_per_day > MAX_POLLS_PER_DAY:
            _logger.error(
                "collection.cadence.rate_out_of_range",
                phase=str(self.phase),
                polls_per_day=self.polls_per_day,
                maximum=MAX_POLLS_PER_DAY,
            )
            raise ValueError(
                f"A polling rate of {self.polls_per_day} per day is outside the supported "
                f"range {MIN_POLLS_PER_DAY}-{MAX_POLLS_PER_DAY}"
            )

    @property
    def interval(self) -> timedelta:
        """The gap between consecutive polls at this rate."""
        return interval_for_rate(self.polls_per_day)

    def next_run_at(self, *, after: datetime) -> datetime:
        """When the cycle following `after` becomes due.

        Measured from when the previous cycle *finished*, not from when it was due. A run
        that was late — a worker was down, a provider was slow — would otherwise have its
        successor fall due immediately, and a backlog of overdue cycles would then run back
        to back at full cost with no gap between them. Drift is the cheaper error.
        """
        return after + self.interval


def interval_for_rate(polls_per_day: int) -> timedelta:
    """Polls per day as a gap. The one place the conversion happens."""
    return timedelta(hours=HOURS_PER_DAY / polls_per_day)


class CadencePolicy(abc.ABC):
    """Decides a title's polling rate, right now."""

    @abc.abstractmethod
    async def decide(self, title: Title, *, now: datetime | None = None) -> CadenceDecision:
        """How hard this title should be polled at this moment, and why."""


class FixedCadencePolicy(CadencePolicy):
    """One rate for every title, whatever phase it is in.

    The opt-out. A deployment that binds this — `COLLECTION_ADAPTIVE_CADENCE=false` — polls
    every title at `COLLECTION_POLLS_PER_DAY` and pays release-week rates for quiet months,
    or dormant rates through an opening weekend. It is kept because "turn the clever thing
    off" has to be one environment variable when adaptive cadence is the code path suspected
    of costing money, and because the phase it reports is the honest one: the calendar's,
    unescalated, so nothing downstream claims a phase drove a rate that it did not.
    """

    def __init__(self, polls_per_day: int) -> None:
        self._polls_per_day = polls_per_day

    async def decide(self, title: Title, *, now: datetime | None = None) -> CadenceDecision:
        calendar_phase = phase_for_day(_utc_day(now), title.release_date)
        return CadenceDecision(
            phase=calendar_phase,
            calendar_phase=calendar_phase,
            polls_per_day=self._polls_per_day,
            is_volume_escalated=False,
        )


class PhaseCadencePolicy(CadencePolicy):
    """The campaign phase sets the rate, and an unexpected spike can raise it.

    Escalation is one step and it is capped at campaign
    (`CadencePhase.is_volume_escalatable`), so the worst a volume heuristic can do to a bill
    is move a title from 2/day to 12/day. Surge rates stay the calendar's to grant.
    """

    def __init__(
        self,
        rates: CadenceRates,
        volume_reader: TitleVolumeReader,
        escalation_rule: VolumeEscalationRule,
    ) -> None:
        self._rates = rates
        self._volume_reader = volume_reader
        self._escalation_rule = escalation_rule

    async def decide(self, title: Title, *, now: datetime | None = None) -> CadenceDecision:
        moment = now or datetime.now(UTC)
        calendar_phase = phase_for_day(_utc_day(moment), title.release_date)

        is_escalated = await self._is_escalated_by_volume(title, calendar_phase, moment)
        phase = calendar_phase.escalated if is_escalated else calendar_phase

        return CadenceDecision(
            phase=phase,
            calendar_phase=calendar_phase,
            polls_per_day=self._rates.for_phase(phase),
            is_volume_escalated=is_escalated,
        )

    async def _is_escalated_by_volume(
        self, title: Title, calendar_phase: CadencePhase, now: datetime
    ) -> bool:
        """Whether observed volume justifies polling harder than the calendar says.

        Asked only of phases a spike is permitted to raise — dormant, and nothing else. The
        two phases this skips are skipped for different reasons, and `is_volume_escalatable`
        holds both: a surge title is already at the top rate so no escalation could raise
        it, and a campaign title is one a spike must not lift to surge rates on its own
        judgement. Either way the volume query is not run, which also spares a database
        round trip on every one of 48 daily enqueues for a title in exactly the state where
        volume is highest and the answer least useful.
        """
        if not calendar_phase.is_volume_escalatable:
            return False

        reading = await self._volume_reader.read(
            title.id, now=now, rule=self._escalation_rule
        )
        if not self._escalation_rule.is_spike(reading):
            return False

        # Warning, not info: a title polling above its planned rate is spending above its
        # planned budget, and somebody reconciling an invoice needs to find this line.
        _logger.warning(
            "collection.cadence.escalated_by_volume",
            title_id=str(title.id),
            calendar_phase=str(calendar_phase),
            escalated_phase=str(calendar_phase.escalated),
            recent_mentions=reading.recent_count,
            baseline_daily_mean=round(reading.baseline_daily_mean, 2),
        )
        return True


def _utc_day(moment: datetime | None) -> date:
    """The calendar day a moment falls on, in UTC — the frame release dates are read in."""
    instant = moment or datetime.now(UTC)
    if instant.tzinfo is None:
        return instant.date()
    return instant.astimezone(UTC).date()
