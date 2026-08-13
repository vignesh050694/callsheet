"""Asking for a stretch of the past, and being told what it costs first (E03-S03).

The request half of backfill: who may ask, what a range must look like to be worth asking
for, what the answer is quoted at, and the queueing of the job. Running it is
`CollectionBackfillRunner` — split because the two have different callers, different
failure modes and different lifetimes. This one answers a request in milliseconds; that one
is minutes of network work in a worker process.

Two rules shape everything here.

**Nothing is spent before somebody sees the price.** The estimate endpoint and the create
endpoint quote through the *same* function, and the quote a studio confirmed is stamped on
the row rather than recomputed later, so the receipt cannot drift from the agreement.

**The range must be in the past.** A backfill that ran up to tomorrow would be paying a
premium to collect what the scheduled poll collects for free, and it would mark posts as
backfilled that were never historical — quietly attaching "incomplete sample" to the live
corpus, which is worse than not having the flag at all.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import (
    PermissionDeniedError,
    ResourceConflictError,
    ResourceNotFoundError,
    ValidationFailedError,
)
from app.models.collection_backfill import CollectionBackfill, CollectionBackfillStatus
from app.models.membership import Membership
from app.models.title import Title
from app.models.user import User
from app.repositories.collection_backfill_repository import CollectionBackfillRepository
from app.repositories.membership_repository import MembershipRepository
from app.repositories.title_repository import TitleRepository
from app.services.collection.backfill_cost import BackfillEstimate, estimate_backfill
from app.services.collection.query_plan import build_query_variants

_logger = structlog.get_logger(__name__)

TITLE_NOT_FOUND_MESSAGE = "Title {id} was not found"
NOT_AN_OWNER_MESSAGE = "Only an owner can spend this organization's budget on a backfill"
RANGE_INVERTED_MESSAGE = "A backfill range has to end after it begins"
RANGE_NOT_HISTORICAL_MESSAGE = (
    "A backfill only collects the past. Scheduled collection already covers everything from "
    "now onwards, so the range has to end no later than this moment."
)
NO_VARIANTS_MESSAGE = (
    "This title's identity set produces no query to run, so there is nothing to backfill"
)
ALREADY_RUNNING_MESSAGE = (
    "This title already has a backfill in progress. Wait for it to finish before asking for "
    "another, so the same range is not paid for twice."
)


@dataclass(frozen=True, slots=True)
class BackfillQuote:
    """What a range would cost, and what would run to produce it."""

    title_id: uuid.UUID
    requested_from: datetime
    requested_until: datetime
    estimate: BackfillEstimate


class CollectionBackfillService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._title_repository = TitleRepository(session)
        self._membership_repository = MembershipRepository(session)
        self._backfill_repository = CollectionBackfillRepository(session)
        self._settings = settings

    async def quote(
        self,
        title_id: uuid.UUID,
        caller: User,
        *,
        requested_from: datetime,
        requested_until: datetime,
        now: datetime | None = None,
    ) -> BackfillQuote:
        """What backfilling this range would cost. Spends nothing and writes nothing."""
        title = await self._require_owned_title(title_id, caller)
        self._validate_range(requested_from, requested_until, now=now or datetime.now(UTC))
        return BackfillQuote(
            title_id=title.id,
            requested_from=requested_from,
            requested_until=requested_until,
            estimate=self._estimate_for(title),
        )

    async def request_backfill(
        self,
        title_id: uuid.UUID,
        caller: User,
        *,
        requested_from: datetime,
        requested_until: datetime,
        now: datetime | None = None,
    ) -> CollectionBackfill:
        """Queues a backfill at the price it was quoted at.

        Queued rather than run inline. A backfill is up to `variants x platforms x page_cap`
        provider calls — minutes of network work — and an HTTP request that held a
        connection open for that long would time out somewhere in between and leave a studio
        unable to tell whether their money had been spent.
        """
        title = await self._require_owned_title(title_id, caller)
        self._validate_range(requested_from, requested_until, now=now or datetime.now(UTC))

        estimate = self._estimate_for(title)
        if await self._backfill_repository.has_pending_for_title(title.id):
            _logger.info("collection.backfill.already_pending", title_id=str(title.id))
            raise ResourceConflictError(ALREADY_RUNNING_MESSAGE)

        backfill = CollectionBackfill(
            title_id=title.id,
            requested_by_user_id=caller.id,
            requested_from=requested_from,
            requested_until=requested_until,
            status=CollectionBackfillStatus.QUEUED,
            page_cap=estimate.pages_per_query,
            estimated_calls=estimate.max_calls,
            estimated_max_cost_usd=estimate.max_cost_usd,
        )
        self._backfill_repository.add(backfill)
        try:
            await self._session.commit()
        except IntegrityError:
            # `uq_collection_backfill_one_pending_per_title` refused a second pending row.
            # The check above lost a race with another request — the ordinary shape of which
            # is a double-click — and the constraint is what turns that into one invoice
            # rather than two.
            await self._session.rollback()
            _logger.info("collection.backfill.lost_pending_race", title_id=str(title.id))
            raise ResourceConflictError(ALREADY_RUNNING_MESSAGE) from None

        _logger.info(
            "collection.backfill.requested",
            backfill_id=str(backfill.id),
            title_id=str(title.id),
            user_id=str(caller.id),
            requested_from=requested_from.isoformat(),
            requested_until=requested_until.isoformat(),
            estimated_calls=estimate.max_calls,
            estimated_max_cost_usd=round(estimate.max_cost_usd, 4),
        )
        return backfill

    async def list_for_title(
        self, title_id: uuid.UUID, caller: User, *, limit: int, offset: int = 0
    ) -> tuple[list[CollectionBackfill], int]:
        """This title's backfill history. Visible to any member, as the title itself is."""
        title, _ = await self._require_member_title(title_id, caller)
        return (
            await self._backfill_repository.list_for_title(title.id, limit=limit, offset=offset),
            await self._backfill_repository.count_for_title(title.id),
        )

    def _estimate_for(self, title: Title) -> BackfillEstimate:
        """The quote, built from the plan that will actually run.

        The variant count comes from `build_query_variants` rather than from the term count,
        because the plan deduplicates and is capped — a title with twelve terms may still run
        five queries, and quoting twelve would inflate the price of every backfill this
        product sells.
        """
        variants = build_query_variants(title, limit=self._settings.collection_variants_per_title)
        if not variants:
            _logger.warning("collection.backfill.no_variants", title_id=str(title.id))
            raise ValidationFailedError(NO_VARIANTS_MESSAGE)
        return estimate_backfill(variant_count=len(variants), settings=self._settings)

    @staticmethod
    def _validate_range(
        requested_from: datetime, requested_until: datetime, *, now: datetime
    ) -> None:
        if requested_until <= requested_from:
            raise ValidationFailedError(RANGE_INVERTED_MESSAGE)
        if requested_until > now:
            raise ValidationFailedError(RANGE_NOT_HISTORICAL_MESSAGE)

    async def _require_member_title(
        self, title_id: uuid.UUID, caller: User
    ) -> tuple[Title, Membership]:
        title = await self._title_repository.get_by_id(title_id)
        if title is None:
            raise ResourceNotFoundError(TITLE_NOT_FOUND_MESSAGE.format(id=title_id))

        membership = await self._membership_repository.get_for_user_and_organization(
            caller.id, title.organization_id
        )
        if membership is None:
            # The same 404 a missing title gives. A non-member must not be able to learn
            # that an unannounced title exists by probing this endpoint.
            _logger.warning(
                "collection.backfill.not_a_member",
                title_id=str(title_id),
                user_id=str(caller.id),
            )
            raise ResourceNotFoundError(TITLE_NOT_FOUND_MESSAGE.format(id=title_id))
        return title, membership

    async def _require_owned_title(self, title_id: uuid.UUID, caller: User) -> Title:
        """Owner-only, because this is the one control in the product that spends money.

        A viewer gets 403 rather than 404: they can already see this title, so pretending it
        is missing would be a lie they can disprove. A non-member never gets this far.
        """
        title, membership = await self._require_member_title(title_id, caller)
        if not membership.role.can_administer_organization:
            _logger.warning(
                "collection.backfill.permission_denied",
                title_id=str(title_id),
                user_id=str(caller.id),
                role=str(membership.role),
            )
            raise PermissionDeniedError(NOT_AN_OWNER_MESSAGE)
        return title
