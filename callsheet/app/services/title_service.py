"""Business logic for titles (E02-S01).

Owns the transaction boundary and every rule. Knows nothing about status codes —
it raises domain errors and lets the API layer translate them.

The rule that matters here is the anchor rule: a short or generic name with no person
attached to it is not collectable, because the query it produces matches everything that
shares the name. The form warns about it; this is where it is actually enforced.
"""

import uuid

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
    normalize_term,
    visible_length,
)
from app.models.membership import Membership
from app.models.title import MIN_UNANCHORED_NAME_LENGTH, Title, TitleTerm, TitleTermType
from app.models.user import User
from app.repositories.membership_repository import MembershipRepository
from app.repositories.title_repository import TitleRepository
from app.schemas.title import TitleCreate

_logger = structlog.get_logger(__name__)

ORGANIZATION_NOT_FOUND_MESSAGE = "Organization {id} was not found"
TITLE_NOT_FOUND_MESSAGE = "Title {id} was not found"
NOT_AN_OWNER_MESSAGE = "Only an owner can add a title to this organization"
UNANCHORED_NAME_MESSAGE = (
    "A title name shorter than {minimum} characters needs at least one cast or crew name "
    "to anchor it, otherwise collection cannot tell it apart from anything else with that name"
)
EMPTY_NAME_MESSAGE = "A title needs a name"
DUPLICATE_TERM_MESSAGE = "This title's identity set contains a duplicate term"


class TitleService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._title_repository = TitleRepository(session)
        self._membership_repository = MembershipRepository(session)

    async def create_title(
        self, organization_id: uuid.UUID, payload: TitleCreate, caller: User
    ) -> Title:
        """Creates the title and its whole identity set as one unit."""
        await self._require_owner(organization_id, caller)

        name = clean_display_value(payload.name)
        if not has_meaningful_content(name):
            raise ValidationFailedError(EMPTY_NAME_MESSAGE)

        terms = self._build_identity_terms(payload)
        self._ensure_name_is_collectable(name, terms)

        title = Title(
            organization_id=organization_id,
            name=name,
            poster_url=payload.poster_url,
        )
        title.terms = terms

        try:
            await self._title_repository.add(title)
            await self._session.commit()
        except IntegrityError:
            # `_build_identity_terms` already dedupes, so the (title_id, term_type,
            # normalized_value) constraint should never fire. It is the backstop for a
            # dedupe bug: a 409 is a survivable answer, a 500 is not. Nothing here reads
            # an ORM attribute — rollback expires them.
            await self._session.rollback()
            _logger.warning(
                "title.create.duplicate_term",
                organization_id=str(organization_id),
            )
            raise ResourceConflictError(DUPLICATE_TERM_MESSAGE) from None

        created_title = await self._title_repository.get_by_id(title.id)
        if created_title is None:  # pragma: no cover — the row was just committed
            raise ResourceNotFoundError(TITLE_NOT_FOUND_MESSAGE.format(id=title.id))

        _logger.info(
            "title.created",
            title_id=str(created_title.id),
            organization_id=str(organization_id),
            term_count=len(created_title.terms),
            user_id=str(caller.id),
        )
        return created_title

    async def get_title(self, title_id: uuid.UUID, caller: User) -> Title:
        """A title is visible to members of the organization that owns it, and nobody else."""
        title = await self._title_repository.get_by_id(title_id)
        if title is None:
            raise ResourceNotFoundError(TITLE_NOT_FOUND_MESSAGE.format(id=title_id))

        membership = await self._membership_repository.get_for_user_and_organization(
            caller.id, title.organization_id
        )
        if membership is None:
            # The same "not found" a missing title gets — a non-member learns nothing
            # about which titles exist, which matters most for unannounced ones.
            _logger.warning(
                "title.access.not_a_member",
                title_id=str(title_id),
                user_id=str(caller.id),
            )
            raise ResourceNotFoundError(TITLE_NOT_FOUND_MESSAGE.format(id=title_id))

        return title

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
        """
        terms = {normalize_term(title.name)}
        terms.update(term.normalized_value for term in title.terms)
        return sorted(term for term in terms if has_meaningful_content(term))

    @staticmethod
    def has_anchor_term(title: Title) -> bool:
        return any(term.term_type.is_anchor for term in title.terms)

    def _build_identity_terms(self, payload: TitleCreate) -> list[TitleTerm]:
        """Folds the form's separate fields into one set, deduped within each kind."""
        field_sources: list[tuple[TitleTermType, list[str]]] = [
            (TitleTermType.ALIAS, payload.aliases),
            (TitleTermType.HASHTAG, payload.hashtags),
            (TitleTermType.CAST, payload.lead_cast),
            (TitleTermType.DIRECTOR, payload.directors),
            (TitleTermType.MUSIC_DIRECTOR, payload.music_directors),
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
                if (term_type, normalized_value) in seen:
                    continue
                seen.add((term_type, normalized_value))
                terms.append(
                    TitleTerm(
                        term_type=term_type,
                        value=clean_display_value(raw_value),
                        normalized_value=normalized_value,
                    )
                )
        return terms

    @staticmethod
    def _ensure_name_is_collectable(name: str, terms: list[TitleTerm]) -> None:
        """The live run's failure case: a bare short name returns its namesakes, not the film.

        Length is counted in visible characters, not code points: padding one glyph with
        combining marks or zero-width joiners must not buy a name its way past the rule.
        """
        if visible_length(name) >= MIN_UNANCHORED_NAME_LENGTH:
            return
        if any(term.term_type.is_anchor for term in terms):
            return

        _logger.warning("title.create.unanchored_name", name_length=len(name))
        raise ValidationFailedError(
            UNANCHORED_NAME_MESSAGE.format(minimum=MIN_UNANCHORED_NAME_LENGTH)
        )

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
