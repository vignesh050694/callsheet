"""Where a title's collection has got to (E03-S01).

The read behind the "Collecting your first mentions" state. A studio that has just finished
setup is looking at an empty screen, and the only question they have is whether that means
*nothing yet* or *nothing wrong*. Those are different states and the product has to tell
them apart, because they look identical and only one of them needs a human.

Four states, and the boundaries are chosen so that no combination of facts falls between
them: never scheduled (which should be impossible and is therefore worth surfacing loudly),
awaiting the first result, collecting, and stalled. `is_awaiting_first_results` is the one
the screen keys off.

The mention count here is **unsegmented**. Organic, trade, owned-media and promotional
accounts are not distinguished until E04-S03, so anything reading this number is reading
activity rather than public conversation, and it says so rather than passing for the
organic figure a viewer would assume.

Since E03-S02 it also carries the **cadence phase**, which is what makes an automatic
escalation visible rather than merely true. That one field is asked of the policy live
rather than read off the queued run, for the reason in `_current_cadence` below.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cadence_phase import CadencePhase
from app.core.exceptions import ResourceNotFoundError
from app.models.collection_run import CollectionRun, CollectionRunStatus
from app.models.title import Title
from app.models.user import User
from app.repositories.collection_run_repository import CollectionRunRepository
from app.repositories.membership_repository import MembershipRepository
from app.repositories.mention_repository import MentionRepository
from app.repositories.title_repository import TitleRepository
from app.services.collection.cadence import CadenceDecision, CadencePolicy

_logger = structlog.get_logger(__name__)

TITLE_NOT_FOUND_MESSAGE = "Title {id} was not found"


@dataclass(frozen=True, slots=True)
class CollectionStatus:
    """One title's collection state, as a screen needs to render it."""

    title_id: uuid.UUID
    mention_count: int
    finished_run_count: int
    last_finished_at: datetime | None
    last_run_status: CollectionRunStatus | None
    last_run_failure_reason: str | None
    next_run_at: datetime | None
    # Always present since E03-S02: the rate is a property of the title's phase, which every
    # title has, rather than of whichever run happened to be lying around.
    polls_per_day: int
    cadence_phase: CadencePhase
    is_volume_escalated: bool
    latest_mention_posted_at: datetime | None

    @property
    def has_ever_run(self) -> bool:
        return self.finished_run_count > 0

    @property
    def is_scheduled(self) -> bool:
        return self.next_run_at is not None

    @property
    def is_awaiting_first_results(self) -> bool:
        """Set up, queued, and nothing has landed yet — the honest empty state.

        True while a title has no mentions *and* is still scheduled to look for some. It
        stops being true the moment either half changes: a mention arrives, or the schedule
        breaks. It is deliberately not tied to "has never run", because the first cycle
        routinely finds nothing on a title announced before anyone is talking about it, and
        telling that studio their setup has finished collecting would be worse than telling
        them it is still going.
        """
        return self.mention_count == 0 and self.is_scheduled

    @property
    def is_stalled(self) -> bool:
        """Nothing is queued. A title in this state will never collect again on its own."""
        return not self.is_scheduled


class CollectionStatusService:
    def __init__(self, session: AsyncSession, cadence: CadencePolicy) -> None:
        self._session = session
        self._title_repository = TitleRepository(session)
        self._membership_repository = MembershipRepository(session)
        self._run_repository = CollectionRunRepository(session)
        self._mention_repository = MentionRepository(session)
        self._cadence = cadence

    async def status_for_title(self, title_id: uuid.UUID, caller: User) -> CollectionStatus:
        """Visible to any member of the owning organization, as the title itself is."""
        title = await self._title_repository.get_by_id(title_id)
        if title is None:
            raise ResourceNotFoundError(TITLE_NOT_FOUND_MESSAGE.format(id=title_id))

        membership = await self._membership_repository.get_for_user_and_organization(
            caller.id, title.organization_id
        )
        if membership is None:
            # The same 404 the title itself gives a non-member — who is tracking what is
            # not something a stranger should be able to probe.
            _logger.warning(
                "collection.status.not_a_member",
                title_id=str(title_id),
                user_id=str(caller.id),
            )
            raise ResourceNotFoundError(TITLE_NOT_FOUND_MESSAGE.format(id=title_id))

        pending = await self._run_repository.next_pending_for_title(title_id)
        latest = await self._run_repository.latest_finished_for_title(title_id)
        cadence = await self._current_cadence(title)

        return CollectionStatus(
            title_id=title_id,
            mention_count=await self._mention_repository.count_for_title(title_id),
            finished_run_count=await self._run_repository.count_finished_for_title(title_id),
            last_finished_at=latest.finished_at if latest else None,
            last_run_status=latest.status if latest else None,
            last_run_failure_reason=self._failure_reason_of(latest),
            next_run_at=pending.scheduled_for if pending else None,
            polls_per_day=cadence.polls_per_day,
            cadence_phase=cadence.phase,
            is_volume_escalated=cadence.is_volume_escalated,
            latest_mention_posted_at=(
                await self._mention_repository.latest_posted_at_for_title(title_id)
            ),
        )

    async def _current_cadence(self, title: Title) -> CadenceDecision:
        """The rate and phase this title is on **now**, asked of the policy directly.

        Not read off the queued run, which is the obvious alternative and is wrong here. The
        run carries the decision made when it was queued, and the whole point of the story is
        that a title crossing into its release-surge window steps up *without anyone doing
        anything* — including without waiting for the queued cycle to run. Reading the stamp
        would show the studio the old phase for up to one full interval after the change, and
        at dormant rates that is twelve hours of a screen saying "quiet period" about a title
        that is already surging.

        The stamped value keeps its own job: it is the history of what each cycle was
        actually scheduled at, and nothing here overwrites it.

        The cost of the live read is that `next_run_at` can lag the rate shown beside it by
        up to one worker tick, until `reconcile_pending_cadence` pulls the queued cycle
        forward. Showing the change late is the worse of the two.
        """
        return await self._cadence.decide(title, now=datetime.now(UTC))

    @staticmethod
    def _failure_reason_of(run: CollectionRun | None) -> str | None:
        """Only reported for outcomes that mean something went wrong.

        A skipped cycle also carries a reason, but it is an explanation rather than a
        fault — "no adapter for this platform yet" is not an incident, and surfacing it in
        the same field as a real failure would train people to ignore the field.
        """
        if run is None or run.status is not CollectionRunStatus.FAILED:
            return None
        return run.failure_reason
