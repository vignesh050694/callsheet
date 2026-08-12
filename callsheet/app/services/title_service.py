"""Business logic for titles (E02-S01).

Owns the transaction boundary and every rule. Knows nothing about status codes —
it raises domain errors and lets the API layer translate them.

The rule that matters here is the anchor rule: a short or generic name with no person
attached to it is not collectable, because the query it produces matches everything that
shares the name. The form warns about it; this is where it is actually enforced.
"""

import uuid
from datetime import date

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    PermissionDeniedError,
    ResourceConflictError,
    ResourceNotFoundError,
    ValidationFailedError,
)
from app.core.identity_terms import (
    clean_display_value,
    has_meaningful_content,
    joiner_folded,
    normalize_term,
)
from app.models.membership import Membership
from app.models.title import (
    MILESTONE_NAME_MAX_LENGTH,
    TITLE_NAME_MAX_LENGTH,
    TITLE_TERM_MAX_LENGTH,
    Title,
    TitleMilestone,
    TitleTerm,
    TitleTermType,
    identity_term_sort_key,
)
from app.models.user import User
from app.repositories.membership_repository import MembershipRepository
from app.repositories.title_repository import TitleRepository
from app.schemas.title import TitleCreate, TitleMilestoneCreate, TitleScheduleUpdate
from app.services.collection_schedule_service import CollectionScheduleService
from app.services.identity_rules import ensure_fits, ensure_name_is_collectable
from app.services.title_access import TitleAccessPolicy

_logger = structlog.get_logger(__name__)

ORGANIZATION_NOT_FOUND_MESSAGE = "Organization {id} was not found"
TITLE_NOT_FOUND_MESSAGE = "Title {id} was not found"
NOT_AN_OWNER_MESSAGE = "Only an owner can add a title to this organization"
NOT_AN_OWNER_SCHEDULE_MESSAGE = "Only an owner can change this title's release date or milestones"
EMPTY_MILESTONE_NAME_MESSAGE = "A campaign milestone needs a name"
EMPTY_NAME_MESSAGE = "A title needs a name"
SELF_EXCLUDING_TERM_MESSAGE = (
    "'{term}' is already part of this title's identity, so excluding it would disqualify "
    "the title's own posts"
)
DUPLICATE_ENTRY_MESSAGE = "This title already contains that identity term or campaign milestone"


class TitleService:
    def __init__(
        self, session: AsyncSession, schedule_service: CollectionScheduleService
    ) -> None:
        self._session = session
        self._title_repository = TitleRepository(session)
        self._membership_repository = MembershipRepository(session)
        self._access_policy = TitleAccessPolicy(session)
        self._schedule_service = schedule_service

    async def create_title(
        self, organization_id: uuid.UUID, payload: TitleCreate, caller: User
    ) -> Title:
        """Creates the title and its whole identity set as one unit."""
        await self._require_owner(organization_id, caller)

        name = clean_display_value(payload.name)
        if not has_meaningful_content(name):
            raise ValidationFailedError(EMPTY_NAME_MESSAGE)
        ensure_fits(name, TITLE_NAME_MAX_LENGTH, "This title name")

        terms = self._build_identity_terms(payload)
        ensure_name_is_collectable(
            name,
            has_anchor_term=any(term.term_type.is_anchor for term in terms),
        )
        self._ensure_exclusions_are_not_self_defeating(name, terms)
        milestones = self._build_milestones(payload.milestones)

        title = Title(
            organization_id=organization_id,
            name=name,
            release_date=payload.release_date,
            poster_url=payload.poster_url,
        )
        title.terms = terms
        title.milestones = milestones

        try:
            await self._title_repository.add(title)
            # Queued inside the same transaction that creates the title (E03-S01). The
            # studio's promise is that collection starts on its own, and a title committed
            # without a cycle owed to it would keep looking correct forever — full identity
            # set, empty dashboard, nothing scheduled to fill it. Either both rows land or
            # neither does.
            await self._schedule_service.queue_first_run(title)
            await self._session.commit()
        except IntegrityError:
            # `_build_identity_terms` and `_build_milestones` already dedupe, so neither
            # unique constraint should fire. They are the backstop for a dedupe bug: a
            # 409 is a survivable answer, a 500 is not. Nothing here reads an ORM
            # attribute — rollback expires them.
            await self._session.rollback()
            _logger.warning(
                "title.create.duplicate_entry",
                organization_id=str(organization_id),
            )
            raise ResourceConflictError(DUPLICATE_ENTRY_MESSAGE) from None

        created_title = await self._title_repository.get_by_id(title.id)
        if created_title is None:  # pragma: no cover — the row was just committed
            raise ResourceNotFoundError(TITLE_NOT_FOUND_MESSAGE.format(id=title.id))

        _logger.info(
            "title.created",
            title_id=str(created_title.id),
            organization_id=str(organization_id),
            term_count=len(created_title.terms),
            milestone_count=len(created_title.milestones),
            release_date=created_title.release_date.isoformat(),
            user_id=str(caller.id),
        )
        return created_title

    async def replace_schedule(
        self, title_id: uuid.UUID, payload: TitleScheduleUpdate, caller: User
    ) -> Title:
        """Sets the release date and the milestone list, and touches nothing else.

        A studio pushes a release date and adds beats as the campaign runs, so this is an
        ordinary edit rather than a correction. It writes two things — the boundary and
        the markers — and never the identity set, so it cannot invalidate anything that
        has already been collected. Charts re-split on the next read because the phase is
        derived there, not stamped on rows at collection time.
        """
        # Through the shared policy, so a caller holding a read-only grant is told their
        # access does not stretch this far (403) rather than that the title is missing —
        # they can see it, so a 404 would be a lie they could disprove. A stranger still
        # gets the 404.
        access = await self._access_policy.require_administrable(
            title_id, caller, owner_message=NOT_AN_OWNER_SCHEDULE_MESSAGE
        )
        title = access.title

        title.release_date = payload.release_date
        self._apply_milestones(title, payload.milestones)

        milestone_count = len(title.milestones)
        release_date = payload.release_date
        try:
            await self._session.commit()
        except IntegrityError:
            # Read nothing off `title` after this — rollback expires every attribute, and
            # touching one here would raise inside the handler instead of returning a 409.
            await self._session.rollback()
            _logger.warning("title.schedule.duplicate_milestone", title_id=str(title_id))
            raise ResourceConflictError(DUPLICATE_ENTRY_MESSAGE) from None

        _logger.info(
            "title.schedule.updated",
            title_id=str(title_id),
            release_date=release_date.isoformat(),
            milestone_count=milestone_count,
            user_id=str(caller.id),
        )

        updated_title = await self._title_repository.get_by_id(title_id)
        if updated_title is None:  # pragma: no cover — the row was just committed
            raise ResourceNotFoundError(TITLE_NOT_FOUND_MESSAGE.format(id=title_id))
        return updated_title

    async def get_title(self, title_id: uuid.UUID, caller: User) -> Title:
        """Visible to the owning organization, and to anyone it has been shared with.

        The rule moved to `TitleAccessPolicy` when titles became shareable (E01-S05).
        Three services used to hold their own copy of it, which was fine while ownership
        was the only way in and became a liability the moment it was not: adding the
        shared case to two of three is a silent hole.
        """
        access = await self._access_policy.require_readable(title_id, caller)
        return access.title

    async def list_titles(
        self, organization_id: uuid.UUID, caller: User, *, limit: int, offset: int
    ) -> tuple[list[Title], int]:
        await self._require_membership(organization_id, caller)
        titles = await self._title_repository.list_for_organization(
            organization_id, limit=limit, offset=offset
        )
        total_count = await self._title_repository.count_for_organization(organization_id)
        return titles, total_count

    @staticmethod
    def collection_terms_for(title: Title) -> list[str]:
        """What collection queries against: the whole identity set, name included.

        Deduped on the normalised form and ordered, so the same title always produces
        the same query regardless of the order the studio typed things in.

        Exclusions are left out. They are the opposite instruction — they disqualify a
        post rather than fetching one — and folding them in here would make the query
        collect precisely the contamination the studio asked to be rid of.
        """
        terms = {normalize_term(title.name)}
        terms.update(
            term.normalized_value for term in title.terms if not term.term_type.is_exclusion
        )
        return sorted(term for term in terms if has_meaningful_content(term))

    @staticmethod
    def excluded_terms_for(title: Title) -> list[str]:
        """The normalised terms that disqualify a post from this title (E02-S03/E02-S05)."""
        return sorted(
            {term.normalized_value for term in title.terms if term.term_type.is_exclusion}
        )

    @staticmethod
    def has_anchor_term(title: Title) -> bool:
        return any(term.term_type.is_anchor for term in title.terms)

    @staticmethod
    def terms_in_order(title: Title) -> list[TitleTerm]:
        """The identity set in its canonical order, sorted here rather than trusted.

        Exactly the reasoning `milestones_in_order` documents below, and it became load
        bearing for the same reason: `Title.terms` declares an `order_by`, but that only
        applies when the query actually loads the collection. On the write path it does
        not — the response to a POST is built from the same session that just created the
        terms, so SQLAlchemy hands back the in-memory insertion order while any later,
        independent read comes back sorted. The identity set would appear to reorder itself
        between creating a title and looking at it again.

        Exclusions are included. This is the whole set as the API reports it, unlike
        `ordered_identity_terms`, which drops them because a query must never be built from
        a term whose purpose is to disqualify a post.
        """
        return sorted(title.terms, key=identity_term_sort_key)

    @staticmethod
    def milestones_in_order(title: Title) -> list[TitleMilestone]:
        """Campaign beats in date order, sorted here rather than trusted from the ORM.

        `Title.milestones` declares `order_by`, but that only applies when the query
        actually loads the collection. On the write path it does not: the response is
        built from the same session that just created the milestones, the collection is
        already populated, and SQLAlchemy hands back the in-memory insertion order
        instead of re-reading. The POST and PUT responses — the exact two a client uses
        to render what it just saved — would come back unordered while an independent
        GET came back sorted.

        Sorting at the point the response is shaped costs nothing for a handful of rows
        and cannot be defeated by session state.

        The normalised name breaks ties. Date alone is not a total order — two beats can
        share a day, and nothing then fixes their relative order, so an UPDATE that moves
        a row on disk can silently swap two markers between one read and the next. The
        unique constraint guarantees (date, normalised name) never ties.
        """
        return sorted(
            title.milestones,
            key=lambda milestone: (milestone.occurs_on, milestone.normalized_name),
        )

    def _build_identity_terms(self, payload: TitleCreate) -> list[TitleTerm]:
        """Folds the form's separate fields into one set, deduped within each kind."""
        field_sources: list[tuple[TitleTermType, list[str]]] = [
            (TitleTermType.ALIAS, payload.aliases),
            (TitleTermType.HASHTAG, payload.hashtags),
            (TitleTermType.CAST, payload.lead_cast),
            (TitleTermType.DIRECTOR, payload.directors),
            (TitleTermType.MUSIC_DIRECTOR, payload.music_directors),
            # Last on purpose: an exclusion is checked against the positive terms, and
            # ordering them behind the rest means the check sees a complete set.
            (TitleTermType.EXCLUSION, payload.exclusions),
        ]

        terms: list[TitleTerm] = []
        seen: set[tuple[TitleTermType, str]] = set()
        for term_type, raw_values in field_sources:
            for raw_value in raw_values:
                normalized_value = normalize_term(raw_value)
                # A term of nothing but invisible characters is not a term. Without this
                # a lone zero-width space would count as a cast member and satisfy the
                # anchor rule, which is exactly what the rule exists to prevent.
                if not has_meaningful_content(normalized_value):
                    continue
                # Deduped on the joiner-folded form — the same equivalence matching and
                # the exclusion guard use. Two spellings of one word are one term, and
                # the first spelling typed is the one kept.
                dedupe_key = (term_type, joiner_folded(normalized_value))
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                display_value = clean_display_value(raw_value)
                # Same NFKC-expansion trap as the title name — see `ensure_fits`.
                ensure_fits(display_value, TITLE_TERM_MAX_LENGTH, "An identity term")
                ensure_fits(normalized_value, TITLE_TERM_MAX_LENGTH, "An identity term")
                terms.append(
                    TitleTerm(
                        term_type=term_type,
                        value=display_value,
                        normalized_value=normalized_value,
                    )
                )
        return terms

    @classmethod
    def _desired_milestones(
        cls,
        payload_milestones: list[TitleMilestoneCreate],
    ) -> dict[tuple[str, date], str]:
        """Campaign beats keyed the way the constraint keys them, mapped to their label.

        A beat is identified by its name *and* its day: "Trailer" on two different dates
        is two beats, and the same beat submitted twice is one. Names are compared
        casefolded and whitespace-collapsed so "Audio launch" and "audio  Launch" do not
        both end up as markers on the same day. Later entries win, so re-typing a beat
        with tidier capitalisation updates the label rather than being discarded.
        """
        desired: dict[tuple[str, date], str] = {}
        for entry in payload_milestones:
            normalized_name = normalize_term(entry.name)
            # A label of nothing but invisible characters paints an unlabelled marker on
            # the chart — same reasoning as identity terms, same rejection.
            if not has_meaningful_content(normalized_name):
                raise ValidationFailedError(EMPTY_MILESTONE_NAME_MESSAGE)
            display_name = clean_display_value(entry.name)
            # Both forms are stored, and both are bounded by the same column width.
            ensure_fits(display_name, MILESTONE_NAME_MAX_LENGTH, "A milestone name")
            ensure_fits(normalized_name, MILESTONE_NAME_MAX_LENGTH, "A milestone name")
            desired[(normalized_name, entry.occurs_on)] = display_name
        return desired

    @classmethod
    def _build_milestones(
        cls, payload_milestones: list[TitleMilestoneCreate]
    ) -> list[TitleMilestone]:
        return [
            TitleMilestone(name=display_name, normalized_name=normalized_name, occurs_on=occurs_on)
            for (normalized_name, occurs_on), display_name in cls._desired_milestones(
                payload_milestones
            ).items()
        ]

    @classmethod
    def _apply_milestones(
        cls, title: Title, payload_milestones: list[TitleMilestoneCreate]
    ) -> None:
        """Diffs the submitted list against what is stored instead of replacing it.

        Replacing the collection outright does not work: SQLAlchemy emits the INSERTs for
        the new rows before the DELETEs for the orphans within one flush, so every beat
        the studio *kept* collides with its own outgoing row on
        `uq_title_milestone_name_date`. Diffing sidesteps that — an unchanged beat is
        never re-inserted.

        It also keeps milestone ids stable across an edit, which matters once spike
        explanations point at them (E04-S05): adding one beat must not renumber the rest.
        """
        desired = cls._desired_milestones(payload_milestones)
        existing = {
            (milestone.normalized_name, milestone.occurs_on): milestone
            for milestone in title.milestones
        }

        for key, milestone in existing.items():
            if key not in desired:
                # `delete-orphan` turns the removal into a DELETE at flush.
                title.milestones.remove(milestone)

        for key, display_name in desired.items():
            kept = existing.get(key)
            if kept is None:
                normalized_name, occurs_on = key
                title.milestones.append(
                    TitleMilestone(
                        name=display_name,
                        normalized_name=normalized_name,
                        occurs_on=occurs_on,
                    )
                )
            else:
                # Same beat, possibly retyped — take the newer spelling.
                kept.name = display_name

    @staticmethod
    def _ensure_exclusions_are_not_self_defeating(name: str, terms: list[TitleTerm]) -> None:
        """An exclusion may not name the title itself, or anything in its identity set.

        The preview seeds these from posts the studio marked "not my title" (E02-S03), so
        a mis-click can propose the film's own hashtag. Stored, that rule would disqualify
        every post the title ever collects — a title that silently gathers nothing, for a
        reason invisible on any screen. It is refused at the door instead.

        Compared on the joiner-folded form, which is the same equivalence matching uses.
        Literal equality would miss the case this guard exists for: the candidate came out
        of a post, so it carries that post's joiners, while the declared term carries the
        studio's — two spellings of one word, and the guard has to see them as one.
        """
        positive_terms = {joiner_folded(normalize_term(name))}
        positive_terms.update(
            joiner_folded(term.normalized_value)
            for term in terms
            if not term.term_type.is_exclusion
        )

        for term in terms:
            if not term.term_type.is_exclusion:
                continue
            if joiner_folded(term.normalized_value) not in positive_terms:
                continue
            _logger.warning("title.create.self_excluding_term", term=term.value)
            raise ValidationFailedError(SELF_EXCLUDING_TERM_MESSAGE.format(term=term.value))

    async def _require_membership(self, organization_id: uuid.UUID, caller: User) -> Membership:
        membership = await self._membership_repository.get_for_user_and_organization(
            caller.id, organization_id
        )
        if membership is None:
            raise ResourceNotFoundError(ORGANIZATION_NOT_FOUND_MESSAGE.format(id=organization_id))
        return membership

    async def _require_owner(self, organization_id: uuid.UUID, caller: User) -> Membership:
        """Adding a title changes the organization, so it is an owner action, not a viewer one."""
        membership = await self._require_membership(organization_id, caller)
        if not membership.role.can_administer_organization:
            _logger.warning(
                "title.permission_denied",
                organization_id=str(organization_id),
                user_id=str(caller.id),
                role=str(membership.role),
            )
            raise PermissionDeniedError(NOT_AN_OWNER_MESSAGE)
        return membership
