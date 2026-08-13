"""Reading a title's recent mention volume against its own history (E03-S02).

The input to the one thing the calendar cannot know: that a title nobody expected to be
talking about is being talked about. A dormant title polls twice a day, so the story's
"unplanned controversy" would otherwise sit undetected for up to twelve hours.

The comparison is always **against the title's own past**, never against a global number. A
Rajinikanth release and an indie music single differ by an order of magnitude in ordinary
volume, and any absolute threshold that escalates one correctly leaves the other either
permanently escalated or permanently blind.
"""

import uuid
from datetime import datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timestamps import as_utc
from app.repositories.mention_repository import MentionRepository
from app.services.collection.cadence import (
    TitleVolumeReader,
    VolumeEscalationRule,
    VolumeReading,
)

_logger = structlog.get_logger(__name__)

# A baseline is a mean, and a mean over less than a day is the day itself. Clamped rather
# than rejected, because a title created this morning has a legitimate volume and no
# history, and refusing to read it would mean it could never escalate.
MINIMUM_BASELINE_DAYS = 1.0


class MentionVolumeReader(TitleVolumeReader):
    """The database-backed reading, in two counts and a division."""

    def __init__(self, session: AsyncSession) -> None:
        self._mention_repository = MentionRepository(session)

    async def read(
        self, title_id: uuid.UUID, *, now: datetime, rule: VolumeEscalationRule
    ) -> VolumeReading:
        # Normalised before any arithmetic: the earliest stored mention comes back naive
        # from SQLite and aware from Postgres, and both get compared against these bounds.
        moment = as_utc(now)
        recent_start = moment - timedelta(hours=rule.recent_hours)
        baseline_start = recent_start - timedelta(days=rule.baseline_days)

        recent_count = await self._mention_repository.count_for_title_posted_between(
            title_id, start=recent_start, end=moment
        )
        baseline_count = await self._mention_repository.count_for_title_posted_between(
            title_id, start=baseline_start, end=recent_start
        )

        observed_days = await self._observed_baseline_days(
            title_id, baseline_start=baseline_start, baseline_end=recent_start
        )
        reading = VolumeReading(
            recent_count=recent_count,
            baseline_daily_mean=baseline_count / observed_days,
        )
        _logger.debug(
            "collection.cadence.volume_read",
            title_id=str(title_id),
            recent_count=recent_count,
            baseline_count=baseline_count,
            observed_days=observed_days,
        )
        return reading

    async def _observed_baseline_days(
        self, title_id: uuid.UUID, *, baseline_start: datetime, baseline_end: datetime
    ) -> float:
        """How many days of history the baseline actually covers.

        A title collected for three days must not have its mean divided by fourteen. That
        would put the baseline at a fifth of its real value and escalate a title whose
        volume never changed — the newest titles, escalated on their first quiet week,
        being exactly the wrong ones to spend surge money on.
        """
        earliest = await self._mention_repository.earliest_posted_at_for_title(title_id)
        if earliest is None:
            return MINIMUM_BASELINE_DAYS

        # Read back through `as_utc`: SQLite hands back a naive value where Postgres hands
        # back an aware one, and subtracting a naive datetime from an aware one raises.
        observed_from = max(as_utc(earliest), baseline_start)
        observed_days = (baseline_end - observed_from) / timedelta(days=1)
        return max(observed_days, MINIMUM_BASELINE_DAYS)
