"""What a backfill will cost, before anyone confirms it (E03-S03).

The story's third and fourth Givens are the whole of this module: the screen must show an
estimate *before* the confirm, and that estimate must come from PER_CALL pricing and a hard
page cap rather than from a guess. Concept note §7 rule 2 is the reason — on a PER_CALL
endpoint the only thing that moves the bill is how many calls are made and how deep they
paginate, so a backfill with no page cap is a backfill with no price.

Pure arithmetic over the endpoint catalogue and the query plan, the same way `cadence_cost`
is pure arithmetic over the calendar. It performs no calls and touches no database, so the
number a studio confirms against is derived from exactly the two things that produce the
spend: how many queries will run, and how deep each is allowed to go.

Every figure here is a **ceiling**, not a forecast. The walk stops early whenever a provider
runs out of pages or the range is covered, and it very often does — a six-week backfill of a
title nobody was discussing yet is one page per query. Quoting the ceiling is the honest
direction to be wrong in: a studio who confirms $2.50 and is charged $0.60 has had a good
surprise, and the reverse would be a bill they never agreed to.
"""

from dataclasses import dataclass

import structlog

from app.core.collection_endpoints import EndpointDescriptor
from app.core.config import Settings
from app.core.exceptions import ServiceUnavailableError
from app.core.platforms import Platform
from app.services.collection.routing import resolve_route

_logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PlatformBackfillEstimate:
    """One platform's share of a backfill, or the reason it has none."""

    platform: Platform
    # Set only when this platform can actually be collected from. A platform with no usable
    # route carries a reason instead, and is never priced at zero — a $0.00 line beside
    # Instagram reads as "free", which is the opposite of "will not run".
    endpoint_key: str | None
    price_model: str | None
    calls: int
    max_cost_usd: float
    unavailable_reason: str | None = None

    @property
    def is_collectable(self) -> bool:
        return self.unavailable_reason is None


@dataclass(frozen=True, slots=True)
class BackfillEstimate:
    """The ceiling a studio confirms against."""

    variants: int
    pages_per_query: int
    page_size: int
    platforms: tuple[PlatformBackfillEstimate, ...]

    @property
    def collectable_platforms(self) -> tuple[PlatformBackfillEstimate, ...]:
        return tuple(platform for platform in self.platforms if platform.is_collectable)

    @property
    def max_calls(self) -> int:
        return sum(platform.calls for platform in self.platforms)

    @property
    def max_cost_usd(self) -> float:
        return sum(platform.max_cost_usd for platform in self.platforms)

    @property
    def can_collect_anything(self) -> bool:
        return bool(self.collectable_platforms)


def max_cost_for_page(endpoint: EndpointDescriptor, page_size: int) -> float:
    """The most one page of this endpoint can cost.

    The two price models diverge here and nowhere else, which is why the catalogue carries
    the model beside the price. PER_CALL is a fixed charge whatever comes back, so depth is
    the only lever. PER_RESULT charges for what it returns, so the *cap* is the price — and
    a flat fee is charged per run, so it lands on every page rather than once.
    """
    if endpoint.price_model.is_billed_per_result:
        return endpoint.flat_fee_usd + endpoint.unit_price_usd * page_size
    return endpoint.flat_fee_usd + endpoint.unit_price_usd


def charged_cost_for_page(endpoint: EndpointDescriptor, items_returned: int) -> float:
    """What one page actually cost, given what came back.

    Same shape as the estimate with the cap replaced by the real count, so a finished
    backfill can be compared against the ceiling it was confirmed at using one formula
    rather than two that can disagree.
    """
    if endpoint.price_model.is_billed_per_result:
        return endpoint.flat_fee_usd + endpoint.unit_price_usd * items_returned
    return endpoint.flat_fee_usd + endpoint.unit_price_usd


def estimate_backfill(*, variant_count: int, settings: Settings) -> BackfillEstimate:
    """The ceiling for backfilling one title, across every platform it collects from.

    Takes the variant count rather than the title, because the plan is built once by the
    caller and estimating from a second plan would let the quoted number describe a
    different set of queries than the one that runs.
    """
    page_cap = settings.collection_backfill_max_pages
    page_size = settings.collection_page_size

    platforms = tuple(
        _estimate_platform(platform, variant_count, page_cap, page_size, settings)
        for platform in settings.collection_platforms
    )
    estimate = BackfillEstimate(
        variants=variant_count,
        pages_per_query=page_cap,
        page_size=page_size,
        platforms=platforms,
    )
    _logger.debug(
        "collection.backfill.estimated",
        variants=variant_count,
        pages_per_query=page_cap,
        calls=estimate.max_calls,
        max_cost_usd=round(estimate.max_cost_usd, 4),
    )
    return estimate


def _estimate_platform(
    platform: Platform,
    variant_count: int,
    page_cap: int,
    page_size: int,
    settings: Settings,
) -> PlatformBackfillEstimate:
    """One platform's ceiling, or the reason it will not be collected from.

    Resolves the route rather than assuming one, so a platform that is configured but has no
    adapter is quoted as unavailable at the moment of the estimate — the same refusal a
    cycle would hit, surfaced before the studio pays for it rather than as an empty result
    afterwards.
    """
    try:
        route = resolve_route(platform, settings)
    except ServiceUnavailableError as error:
        return PlatformBackfillEstimate(
            platform=platform,
            endpoint_key=None,
            price_model=None,
            calls=0,
            max_cost_usd=0.0,
            unavailable_reason=error.message,
        )

    calls = variant_count * page_cap
    return PlatformBackfillEstimate(
        platform=platform,
        endpoint_key=route.endpoint.key,
        price_model=str(route.endpoint.price_model),
        calls=calls,
        max_cost_usd=calls * max_cost_for_page(route.endpoint, page_size),
    )
