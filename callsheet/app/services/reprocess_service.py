"""Re-deriving a title's corpus from stored payloads, without paying again (E03-S04).

The concept note calls this the single most important architectural constraint: analysis
is the budget risk at $90-$900 per title, and a pipeline that could not be re-run over a
stored corpus would multiply it every time a model improved.

**This service cannot spend money.** Not by policy — structurally. It is constructed
without a `CollectionSource` and without a transport, so there is no path from here to a
provider. The guarantee is the absence of a dependency rather than a rule someone has to
remember, which means it survives changes made by people who never read this docstring.

Two things are re-derived, and the difference matters:

* **The mention**, re-read from its raw payload through the adapter that serves its
  endpoint today. This is what makes a mapping fix retroactive — a payload stored under a
  broken adapter version becomes a correct mention with no second call.
* **The derived fields**, recomputed by whichever analysis pipeline version is asked for
  and written beside the previous version's, never over it.
"""

import enum
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ResourceNotFoundError, ValidationFailedError
from app.models.mention import Mention, MentionRawPayload
from app.models.mention_analysis import MentionAnalysis
from app.repositories.mention_analysis_repository import MentionAnalysisRepository
from app.repositories.mention_repository import MentionRepository
from app.repositories.title_repository import TitleRepository
from app.services.analysis.mention_analyzer import (
    AnalysisVerdict,
    AnalyzableMention,
    MentionAnalyzer,
)
from app.services.collection.adapters import get_adapter
from app.services.collection.payload_values import PayloadShapeError

_logger = structlog.get_logger(__name__)

TITLE_NOT_FOUND_MESSAGE = "Title {id} was not found"
INVALID_WINDOW_MESSAGE = "The reprocess window ends before it starts"

# How many mentions are re-derived per batch. Bounded so a six-week corpus is walked in
# steady, resumable steps rather than loaded into memory at once.
REPROCESS_BATCH_SIZE = 200


class _RemapOutcome(enum.Enum):
    """What re-reading one stored payload did.

    Four outcomes, because three of them mean "no update was written" and only one of
    those is healthy. Collapsing any of them into `UNCHANGED` is how a rotting corpus
    stays invisible — the run reports success and an operator has no number to look at.

    `UNVERIFIABLE` is the case where nothing is wrong with the payload at all: its
    endpoint has no adapter registered any more, so this application currently has no way
    to check whether the mention still matches what was collected. That is a
    configuration problem rather than a data problem, and it needs its own answer because
    the fix is different — restore the adapter, rather than investigate the post.
    """

    UNCHANGED = "unchanged"
    UPDATED = "updated"
    UNREADABLE = "unreadable"
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True, slots=True)
class ReprocessResult:
    """What a run did, in the terms the person who triggered it will ask about."""

    title_id: uuid.UUID
    pipeline_version: str
    examined: int
    analyzed: int
    already_analyzed: int
    remapped: int
    unreadable: int
    missing_payload: int
    unverifiable: int = 0
    collection_calls: int = 0

    @property
    def has_spent_nothing(self) -> bool:
        """Always true, and asserted rather than assumed — see the module docstring."""
        return self.collection_calls == 0


class ReprocessService:
    def __init__(
        self,
        session: AsyncSession,
        analyzer: MentionAnalyzer,
    ) -> None:
        self._session = session
        self._title_repository = TitleRepository(session)
        self._mention_repository = MentionRepository(session)
        self._analysis_repository = MentionAnalysisRepository(session)
        self._analyzer = analyzer

    async def reprocess_title(
        self,
        title_id: uuid.UUID,
        *,
        posted_from: datetime | None = None,
        posted_until: datetime | None = None,
    ) -> ReprocessResult:
        """Re-derives one title's corpus within a window, reading only stored payloads."""
        await self._require_title(title_id)
        self._ensure_window_is_usable(posted_from, posted_until)

        version = self._analyzer.pipeline_version
        started_at = time.perf_counter()
        totals = _RunningTotals()

        async for batch in self._walk_corpus(title_id, posted_from, posted_until):
            await self._reprocess_batch(title_id, batch, version, totals)
            # Committed per batch, not once at the end. A six-week corpus is many batches
            # and the analyzer is a network call that will fail sometimes; holding one
            # transaction across the whole walk means a failure in the last batch throws
            # away every repair and every verdict computed before it. Because analyses are
            # versioned and skipped when already present, a crashed run resumes from where
            # it stopped instead of starting over — which is the difference between a
            # reprocess someone will run and one they will not dare to.
            await self._session.commit()

        result = totals.to_result(title_id, version)
        _logger.info(
            "reprocess.title.completed",
            title_id=str(title_id),
            pipeline_version=version,
            examined=result.examined,
            analyzed=result.analyzed,
            already_analyzed=result.already_analyzed,
            remapped=result.remapped,
            unreadable=result.unreadable,
            unverifiable=result.unverifiable,
            missing_payload=result.missing_payload,
            collection_calls=result.collection_calls,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 1),
        )
        return result

    async def _walk_corpus(
        self,
        title_id: uuid.UUID,
        posted_from: datetime | None,
        posted_until: datetime | None,
    ) -> AsyncIterator[list[Mention]]:
        """Yields the corpus in keyset-paged batches, ordered by primary key.

        The cursor is a mention id, which nothing in this walk can change — see
        `MentionRepository.list_for_title_in_window` for why paging by `posted_at` would
        be unsafe here even though that is the column the window filters on.
        """
        cursor_id: uuid.UUID | None = None
        while True:
            batch = await self._mention_repository.list_for_title_in_window(
                title_id,
                posted_from=posted_from,
                posted_until=posted_until,
                limit=REPROCESS_BATCH_SIZE,
                after_id=cursor_id,
            )
            if not batch:
                return
            cursor_id = batch[-1].id
            yield batch

    async def _reprocess_batch(
        self,
        title_id: uuid.UUID,
        batch: list[Mention],
        version: str,
        totals: "_RunningTotals",
    ) -> None:
        """Re-reads a batch from its payloads, then analyses whatever this version has not."""
        totals.examined += len(batch)
        mention_ids = [mention.id for mention in batch]
        payloads = await self._mention_repository.payloads_for_mentions(mention_ids)

        for mention in batch:
            payload = payloads.get(mention.id)
            if payload is None:
                # Nothing to re-derive from. The mention stands as collected; it is
                # counted so a corpus that predates payload storage is visible rather
                # than silently treated as up to date.
                totals.missing_payload += 1
                continue
            outcome = self._remap(mention, payload)
            if outcome is _RemapOutcome.UPDATED:
                totals.remapped += 1
            elif outcome is _RemapOutcome.UNREADABLE:
                totals.unreadable += 1
            elif outcome is _RemapOutcome.UNVERIFIABLE:
                totals.unverifiable += 1

        already = await self._analysis_repository.analyzed_mention_ids(version, mention_ids)
        totals.already_analyzed += len(already)

        pending = [mention for mention in batch if mention.id not in already]
        if pending:
            totals.analyzed += await self._analyze(title_id, pending, version)

    def _remap(self, mention: Mention, payload: MentionRawPayload) -> "_RemapOutcome":
        """Re-reads a stored payload through today's adapter, updating what changed.

        Three outcomes, not two. "Nothing moved" and "this can no longer be read at all"
        look identical to a caller that only asks whether something changed, and they mean
        opposite things: the first is the healthy common case, the second is a corpus
        quietly rotting. Reporting them apart is what lets an operator tell whether a
        mapping fix worked.

        A failure leaves the payload completely alone — not even its error annotation is
        rewritten. It is the artefact that was paid for, and the next adapter version gets
        exactly the same bytes this one saw.
        """
        adapter = get_adapter(payload.endpoint_key)
        if adapter is None:
            # No mapping is configured for this endpoint any more. Not the payload's
            # fault, and not something a later run fixes by itself, so it is logged
            # rather than counted against the corpus.
            _logger.warning(
                "reprocess.remap.no_adapter",
                mention_id=str(mention.id),
                endpoint=payload.endpoint_key,
            )
            return _RemapOutcome.UNVERIFIABLE
        try:
            remapped = adapter.to_mention(payload.payload)
        except PayloadShapeError as error:
            _logger.warning(
                "reprocess.remap.still_unreadable",
                mention_id=str(mention.id),
                endpoint=payload.endpoint_key,
                adapter_version=adapter.version,
                reason=str(error),
            )
            return _RemapOutcome.UNREADABLE

        changed = False
        for attribute, value in (
            ("text", remapped.text),
            ("permalink", remapped.permalink),
            ("author_handle", remapped.author_handle),
            ("author_display_name", remapped.author_display_name),
            ("author_follower_count", remapped.author_follower_count),
            ("platform_reported_language", remapped.platform_reported_language),
            ("posted_at", remapped.posted_at),
            ("hashtags", list(remapped.hashtags)),
        ):
            if _differs(getattr(mention, attribute), value):
                setattr(mention, attribute, value)
                changed = True

        if not changed:
            return _RemapOutcome.UNCHANGED

        payload.adapter_version = adapter.version
        payload.normalization_error = None
        _logger.info(
            "reprocess.remap.updated",
            mention_id=str(mention.id),
            endpoint=payload.endpoint_key,
            adapter_version=adapter.version,
        )
        return _RemapOutcome.UPDATED

    async def _analyze(
        self, title_id: uuid.UUID, mentions: list[Mention], version: str
    ) -> int:
        """Runs the analyzer over a batch and stores its verdicts under this version."""
        analyzed_at = datetime.now(UTC)
        verdicts = await self._analyzer.analyze(
            [self._to_analyzable(mention) for mention in mentions]
        )

        by_mention_id = {verdict.mention_id: verdict for verdict in verdicts}
        rows = [
            self._to_row(title_id, mention, by_mention_id[str(mention.id)], version, analyzed_at)
            for mention in mentions
            if str(mention.id) in by_mention_id
        ]
        await self._analysis_repository.add_all(rows)

        skipped = len(mentions) - len(rows)
        if skipped:
            # An analyzer that returns nothing for a mention has declined to judge it.
            # Recorded as a gap rather than written as a null verdict, so a later run can
            # pick it up.
            _logger.warning(
                "reprocess.analyze.incomplete",
                title_id=str(title_id),
                pipeline_version=version,
                requested=len(mentions),
                returned=len(rows),
            )
        return len(rows)

    @staticmethod
    def _to_analyzable(mention: Mention) -> AnalyzableMention:
        return AnalyzableMention(
            mention_id=str(mention.id),
            platform=mention.platform,
            text=mention.text,
            posted_at=mention.posted_at,
            author_handle=mention.author_handle,
            author_follower_count=mention.author_follower_count,
            hashtags=list(mention.hashtags or []),
            platform_reported_language=mention.platform_reported_language,
        )

    @staticmethod
    def _to_row(
        title_id: uuid.UUID,
        mention: Mention,
        verdict: AnalysisVerdict,
        version: str,
        analyzed_at: datetime,
    ) -> MentionAnalysis:
        return MentionAnalysis(
            mention_id=mention.id,
            title_id=title_id,
            pipeline_version=version,
            detected_language=verdict.detected_language,
            language_confidence=verdict.language_confidence,
            is_code_mixed=verdict.is_code_mixed,
            account_type=verdict.account_type,
            account_type_confidence=verdict.account_type_confidence,
            sentiment_label=verdict.sentiment_label,
            sentiment_confidence=verdict.sentiment_confidence,
            themes=list(verdict.themes),
            analyzed_at=analyzed_at,
        )

    @staticmethod
    def _ensure_window_is_usable(
        posted_from: datetime | None, posted_until: datetime | None
    ) -> None:
        if posted_from is not None and posted_until is not None and posted_until < posted_from:
            raise ValidationFailedError(INVALID_WINDOW_MESSAGE)

    async def _require_title(self, title_id: uuid.UUID) -> None:
        title = await self._title_repository.get_by_id(title_id)
        if title is None:
            _logger.warning("reprocess.title.not_found", title_id=str(title_id))
            raise ResourceNotFoundError(TITLE_NOT_FOUND_MESSAGE.format(id=title_id))


def _differs(stored: object, remapped: object) -> bool:
    """Whether a re-read value actually moved, comparing timestamps as instants.

    Datetimes need their own rule. Postgres hands back an aware value; SQLite, which the
    test suite runs on, hands back a naive one holding the same UTC instant. Python's `!=`
    calls those unequal without complaint — unlike `<`, which would at least raise — so a
    plain comparison reports every mention as remapped on every run, dirties every row it
    touched, and turns the `remapped` count into noise exactly where someone would be
    relying on it to tell them whether a mapping fix did anything.
    """
    if isinstance(stored, datetime) and isinstance(remapped, datetime):
        return _as_utc(stored) != _as_utc(remapped)
    return stored != remapped


def _as_utc(value: datetime) -> datetime:
    """A naive value is stored UTC — that is the only thing this application writes."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass
class _RunningTotals:
    examined: int = 0
    analyzed: int = 0
    already_analyzed: int = 0
    remapped: int = 0
    unreadable: int = 0
    unverifiable: int = 0
    missing_payload: int = 0

    def to_result(self, title_id: uuid.UUID, version: str) -> ReprocessResult:
        return ReprocessResult(
            title_id=title_id,
            pipeline_version=version,
            examined=self.examined,
            analyzed=self.analyzed,
            already_analyzed=self.already_analyzed,
            remapped=self.remapped,
            unreadable=self.unreadable,
            unverifiable=self.unverifiable,
            missing_payload=self.missing_payload,
        )
