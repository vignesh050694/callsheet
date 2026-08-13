"""Shared FastAPI dependencies.

Controllers declare what they need here rather than constructing services inline, which
keeps route bodies to "parse input, call service, shape response".
"""

import uuid
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.models.user import User
from app.services.alias_discovery_service import AliasDiscoveryService
from app.services.analysis.mention_analyzer import (
    MentionAnalyzer,
    UnconfiguredMentionAnalyzer,
)
from app.services.collection.cadence import (
    CadencePolicy,
    CadenceRates,
    FixedCadencePolicy,
    PhaseCadencePolicy,
    VolumeEscalationRule,
)
from app.services.collection.monid_source import (
    MonidCollectionSource,
    MonidTransport,
    UnconfiguredMonidTransport,
)
from app.services.collection.monid_transport import HttpMonidTransport
from app.services.collection.preview_source import CollectionSourcePreviewSearch
from app.services.collection.source import CollectionSource
from app.services.collection.spend_policy import SpendPolicy, UnrestrictedSpendPolicy
from app.services.collection.volume import MentionVolumeReader
from app.services.collection_run_service import CollectionRunService
from app.services.collection_schedule_service import CollectionScheduleService
from app.services.collection_service import CollectionService
from app.services.collection_status_service import CollectionStatusService
from app.services.invitation_notifier import InvitationNotifier
from app.services.invitation_service import InvitationService
from app.services.mention_feed_service import MentionFeedService
from app.services.organization_service import OrganizationService
from app.services.preview_search import PreviewSearch, UnconfiguredPreviewSearch
from app.services.reprocess_service import ReprocessService
from app.services.title_exclusion_service import TitleExclusionService
from app.services.title_invitation_service import TitleInvitationService
from app.services.title_membership_service import TitleMembershipService
from app.services.title_preview_service import TitlePreviewService
from app.services.title_service import TitleService
from app.services.title_sharing_service import TitleSharingService
from app.services.user_service import UserService

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def get_organization_service(session: DbSession) -> OrganizationService:
    return OrganizationService(session)


OrganizationServiceDep = Annotated[OrganizationService, Depends(get_organization_service)]


def get_user_service(session: DbSession) -> UserService:
    return UserService(session)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]


def get_invitation_notifier() -> InvitationNotifier:
    """Overridable seam: a test asserts against it, a real mailer replaces it."""
    return InvitationNotifier()


InvitationNotifierDep = Annotated[InvitationNotifier, Depends(get_invitation_notifier)]


def get_invitation_service(
    session: DbSession, notifier: InvitationNotifierDep
) -> InvitationService:
    return InvitationService(session, notifier)


InvitationServiceDep = Annotated[InvitationService, Depends(get_invitation_service)]


def get_title_membership_service(
    session: DbSession, notifier: InvitationNotifierDep
) -> TitleMembershipService:
    """Shares the notifier seam with organization invitations — one place to swap in a mailer."""
    return TitleMembershipService(session, notifier)


TitleMembershipServiceDep = Annotated[TitleMembershipService, Depends(get_title_membership_service)]


def get_title_invitation_service(session: DbSession) -> TitleInvitationService:
    """No notifier: accepting sends nothing. The artist is already here."""
    return TitleInvitationService(session)


TitleInvitationServiceDep = Annotated[TitleInvitationService, Depends(get_title_invitation_service)]


def get_title_sharing_service(session: DbSession) -> TitleSharingService:
    """Sharing sends nothing — the agency organization is already on the platform."""
    return TitleSharingService(session)


TitleSharingServiceDep = Annotated[TitleSharingService, Depends(get_title_sharing_service)]


def get_alias_discovery_service(session: DbSession) -> AliasDiscoveryService:
    """Deliberately assembled without a collection source, exactly as `ReprocessService` is.

    Approving an alias re-matches the corpus already collected, and that path must never
    be able to pay for a fresh one. Not passing it anything that can reach a provider is a
    stronger guarantee than a rule inside it, because it survives changes made by people
    who have not read why.
    """
    return AliasDiscoveryService(session)


AliasDiscoveryServiceDep = Annotated[AliasDiscoveryService, Depends(get_alias_discovery_service)]


def get_title_exclusion_service(session: DbSession) -> TitleExclusionService:
    """Assembled without a collection source, for the same reason the alias service is.

    Excluding a term re-reads posts already stored and marks them; lifting the rule gives
    them back. Neither may cost anything, and the absence of a dependency that could spend
    is a stronger guarantee than a rule inside the service.
    """
    return TitleExclusionService(session)


TitleExclusionServiceDep = Annotated[TitleExclusionService, Depends(get_title_exclusion_service)]


def get_mention_feed_service(session: DbSession) -> MentionFeedService:
    return MentionFeedService(session)


MentionFeedServiceDep = Annotated[MentionFeedService, Depends(get_mention_feed_service)]


def get_app_settings() -> Settings:
    """Settings as a dependency, so a test can point a platform at another endpoint."""
    return get_settings()


AppSettings = Annotated[Settings, Depends(get_app_settings)]


def get_cadence_policy(session: DbSession, settings: AppSettings) -> CadencePolicy:
    """How often titles are polled (E03-S02).

    The single binding the whole cadence question resolves through — nothing else in the
    codebase multiplies a rate by anything. `COLLECTION_ADAPTIVE_CADENCE=false` swaps the
    phase-driven policy for the flat one, which is the escape hatch for a deployment where
    adaptive cadence is the code path suspected of costing money.
    """
    if not settings.collection_adaptive_cadence:
        return FixedCadencePolicy(settings.collection_polls_per_day)
    return PhaseCadencePolicy(
        CadenceRates.from_settings(settings),
        MentionVolumeReader(session),
        VolumeEscalationRule.from_settings(settings),
    )


CadencePolicyDep = Annotated[CadencePolicy, Depends(get_cadence_policy)]


def get_collection_schedule_service(
    session: DbSession, cadence: CadencePolicyDep
) -> CollectionScheduleService:
    return CollectionScheduleService(session, cadence)


CollectionScheduleServiceDep = Annotated[
    CollectionScheduleService, Depends(get_collection_schedule_service)
]


def get_title_service(
    session: DbSession, schedule_service: CollectionScheduleServiceDep
) -> TitleService:
    """The scheduler is a required collaborator, not an optional one.

    A title that exists with no collection cycle owed to it is the exact failure E03-S01
    removes, and it is invisible — the title has an identity set, a dashboard, and no
    mentions, which is what a film nobody is discussing also looks like. Making the
    dependency required means that state cannot be reached by forgetting to wire something
    up; it can only be reached by deleting a queued run.
    """
    return TitleService(session, schedule_service)


TitleServiceDep = Annotated[TitleService, Depends(get_title_service)]


def get_monid_transport(settings: AppSettings) -> MonidTransport:
    """The one seam that leaves the process.

    Bound on whether a credential exists and on nothing else. Without one the refusing
    implementation stays: a deployment with no key must say "not configured on this
    deployment", which is a true statement someone can act on, rather than failing per
    call with a vendor's 401 that reads like a bug in the request.
    """
    if not settings.is_collection_configured:
        return UnconfiguredMonidTransport()
    return HttpMonidTransport(settings)


MonidTransportDep = Annotated[MonidTransport, Depends(get_monid_transport)]


def get_collection_source(transport: MonidTransportDep, settings: AppSettings) -> CollectionSource:
    return MonidCollectionSource(transport, settings)


CollectionSourceDep = Annotated[CollectionSource, Depends(get_collection_source)]


def get_preview_search(source: CollectionSourceDep, settings: AppSettings) -> PreviewSearch:
    """The setup preview's search, which is collection's search (E02-S03 into E03-S07).

    Bound on the same one question the transport is, so the two cannot disagree. That
    matters more than the small duplication it looks like: a deployment where the preview
    was live and collection was not would show a studio real posts and then hand them an
    empty dashboard, and each half would look correct on its own.

    Unconfigured keeps its *own* refusal rather than inheriting the transport's, because
    the two messages are for people in different situations. Collection's says nothing can
    be polled; the preview's adds the thing a studio in the middle of setup needs to hear —
    that they can save the title anyway and collection starts when it exists.
    """
    if not settings.is_collection_configured:
        return UnconfiguredPreviewSearch()
    return CollectionSourcePreviewSearch(source)


PreviewSearchDep = Annotated[PreviewSearch, Depends(get_preview_search)]


def get_title_preview_service(session: DbSession, search: PreviewSearchDep) -> TitlePreviewService:
    return TitlePreviewService(session, search)


TitlePreviewServiceDep = Annotated[TitlePreviewService, Depends(get_title_preview_service)]


def get_collection_service(session: DbSession, source: CollectionSourceDep) -> CollectionService:
    return CollectionService(session, source)


CollectionServiceDep = Annotated[CollectionService, Depends(get_collection_service)]


def get_spend_policy() -> SpendPolicy:
    """Whether an organization may pay for another cycle. E09 replaces this binding.

    Permissive by default, and it logs that it is being permissive rather than staying
    silent — an ungoverned deployment must not read as a governed one with generous limits.
    """
    return UnrestrictedSpendPolicy()


SpendPolicyDep = Annotated[SpendPolicy, Depends(get_spend_policy)]


def get_collection_run_service(
    session: DbSession,
    collection_service: CollectionServiceDep,
    schedule_service: CollectionScheduleServiceDep,
    spend_policy: SpendPolicyDep,
    settings: AppSettings,
) -> CollectionRunService:
    return CollectionRunService(
        session, collection_service, schedule_service, spend_policy, settings
    )


CollectionRunServiceDep = Annotated[CollectionRunService, Depends(get_collection_run_service)]


def get_collection_status_service(
    session: DbSession, cadence: CadencePolicyDep
) -> CollectionStatusService:
    return CollectionStatusService(session, cadence)


CollectionStatusServiceDep = Annotated[
    CollectionStatusService, Depends(get_collection_status_service)
]


def get_mention_analyzer() -> MentionAnalyzer:
    """The analysis seam. E04 supplies a real pipeline; until then this refuses."""
    return UnconfiguredMentionAnalyzer()


MentionAnalyzerDep = Annotated[MentionAnalyzer, Depends(get_mention_analyzer)]


def get_reprocess_service(session: DbSession, analyzer: MentionAnalyzerDep) -> ReprocessService:
    """Deliberately assembled without a collection source.

    A reprocess re-derives from stored payloads and must never be able to spend. Not
    passing it anything that can call a provider is a stronger guarantee than any check
    inside it, because it survives changes made by people who have not read why.
    """
    return ReprocessService(session, analyzer)


ReprocessServiceDep = Annotated[ReprocessService, Depends(get_reprocess_service)]


async def get_current_user(
    user_service: UserServiceDep,
    x_user_id: Annotated[uuid.UUID | None, Header(alias="X-User-Id")] = None,
) -> User:
    """The caller, as asserted by `X-User-Id`.

    This is the seam a real session layer will replace. It is deliberately the only
    place the header is read, so swapping it out touches one function rather than
    every route that needs to know who is asking.
    """
    return await user_service.resolve_caller(x_user_id)


CurrentUser = Annotated[User, Depends(get_current_user)]
