"""The Monid-backed collection source (E03-S07).

Composes the three pieces that make a provider swap a configuration change: routing picks
the endpoint, the adapter translates both ways, and the transport is the one thing that
actually leaves the process.

The transport is a seam rather than an HTTP client. What Monid needs — retries, run
polling, spend controls, a real key — is the substance of E03-S01 and E09, and writing an
untested client here would put fiction behind an interface whose entire purpose is that
you can trust what is behind it. The default binding refuses; a test binds a replay of the
committed captures, which is how both providers are exercised without spending anything.
"""

import abc
import time
from typing import Any

import structlog

from app.core.collection_endpoints import EndpointDescriptor
from app.core.config import Settings
from app.core.exceptions import ServiceUnavailableError
from app.core.platforms import Platform
from app.services.collection.adapters import ProviderRequest
from app.services.collection.payload_values import PayloadShapeError
from app.services.collection.routing import CollectionRoute, resolve_route
from app.services.collection.source import (
    COLLECTION_UNAVAILABLE_MESSAGE,
    CollectedItem,
    CollectionPage,
    CollectionSource,
    CollectionWindow,
)

_logger = structlog.get_logger(__name__)

UNCAPPED_PER_RESULT_MESSAGE = (
    "Endpoint {key!r} is billed per result and was asked for {limit} results, which is "
    "not a usable cap"
)


class MonidTransport(abc.ABC):
    """The only thing in the collection layer that talks to the outside world."""

    @abc.abstractmethod
    async def run(self, endpoint: EndpointDescriptor, request: ProviderRequest) -> Any:
        """Executes one call and returns the provider's response body, undisturbed."""


class UnconfiguredMonidTransport(MonidTransport):
    """No key, no calls. Refuses rather than returning an empty page."""

    async def run(self, endpoint: EndpointDescriptor, request: ProviderRequest) -> Any:
        _logger.warning(
            "collection.transport.unconfigured",
            endpoint=endpoint.key,
            provider=endpoint.provider,
        )
        raise ServiceUnavailableError(COLLECTION_UNAVAILABLE_MESSAGE)


class MonidCollectionSource(CollectionSource):
    def __init__(self, transport: MonidTransport, settings: Settings) -> None:
        self._transport = transport
        self._settings = settings

    async def fetch(
        self,
        platform: Platform,
        query: str,
        *,
        page: str | None = None,
        limit: int,
        window: CollectionWindow | None = None,
    ) -> CollectionPage:
        """One page, through whichever endpoint this platform is currently pointed at."""
        route = resolve_route(platform, self._settings)
        self._ensure_cap_is_usable(route, limit)

        response = await self._call(route, query, page=page, limit=limit, window=window)
        items = self._read_items(route, response, limit)

        return CollectionPage(
            platform=platform,
            endpoint=route.endpoint,
            adapter_version=route.adapter.version,
            items=items,
            next_page=route.adapter.read_next_page(response),
        )

    @staticmethod
    def _ensure_cap_is_usable(route: CollectionRoute, limit: int) -> None:
        """On a PER_RESULT endpoint the cap is the invoice, so a bad one is refused here.

        Deliberately not a spend policy — that is E09's, and it belongs somewhere that can
        see a whole workspace's budget. This is the narrower structural rule: a per-result
        endpoint asked for an unbounded number of results has no ceiling at all, and the
        port must not be able to express that call.
        """
        if route.endpoint.requires_result_cap and limit <= 0:
            _logger.error(
                "collection.fetch.uncapped_per_result",
                endpoint=route.endpoint.key,
                limit=limit,
            )
            raise ServiceUnavailableError(
                UNCAPPED_PER_RESULT_MESSAGE.format(key=route.endpoint.key, limit=limit)
            )

    async def _call(
        self,
        route: CollectionRoute,
        query: str,
        *,
        page: str | None,
        limit: int,
        window: CollectionWindow | None,
    ) -> Any:
        """Runs the call and logs it with timing, the way a request is logged.

        A poll is this layer's unit of work and its unit of spend, so it gets the same
        treatment an inbound request gets from the logging middleware: what was asked,
        which endpoint answered, and how long it took.
        """
        request = route.adapter.build_request(query, page=page, limit=limit, window=window)
        started_at = time.perf_counter()
        try:
            response = await self._transport.run(route.endpoint, request)
        except ServiceUnavailableError:
            raise
        except Exception:
            _logger.exception(
                "collection.fetch.failed",
                platform=str(route.platform),
                endpoint=route.endpoint.key,
                provider=route.endpoint.provider,
            )
            raise

        _logger.info(
            "collection.fetch.completed",
            platform=str(route.platform),
            endpoint=route.endpoint.key,
            provider=route.endpoint.provider,
            price_model=str(route.endpoint.price_model),
            paged=page is not None,
            # A historical call and a live one bill identically and read very differently on
            # an invoice, so the window is on the line that records the spend.
            windowed=window is not None,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 1),
        )
        return response

    @staticmethod
    def _read_items(route: CollectionRoute, response: Any, limit: int) -> list[CollectedItem]:
        """Normalises each item, keeping the raw payload whatever happens to it.

        The cap is re-applied here as well as passed down, for the reason the preview
        re-applies its own: the port cannot enforce what a provider chooses to return, and
        a page wider than the caller asked for is both an unbudgeted cost and a poll that
        no longer resembles the one the schedule was built around.
        """
        raw_items = route.adapter.read_items(response)
        if len(raw_items) > limit:
            _logger.warning(
                "collection.fetch.over_cap",
                endpoint=route.endpoint.key,
                returned=len(raw_items),
                limit=limit,
            )
            raw_items = raw_items[:limit]

        items: list[CollectedItem] = []
        for raw_item in raw_items:
            external_id = route.adapter.read_external_id(raw_item)
            try:
                mention = route.adapter.to_mention(raw_item)
            except PayloadShapeError as error:
                _logger.warning(
                    "collection.normalize.failed",
                    endpoint=route.endpoint.key,
                    adapter_version=route.adapter.version,
                    external_id=external_id,
                    reason=str(error),
                )
                if external_id is None:
                    # Nothing to recognise this item by on the next poll, so it cannot be
                    # deduplicated and will be stored again each cycle. Logged at error
                    # because it means the adapter cannot find the provider's own primary
                    # key — a mapping that wrong needs a human, not a retry.
                    _logger.error(
                        "collection.normalize.unidentifiable",
                        endpoint=route.endpoint.key,
                        adapter_version=route.adapter.version,
                    )
                items.append(
                    CollectedItem(
                        raw_payload=raw_item,
                        external_id=external_id,
                        normalization_error=str(error),
                    )
                )
                continue
            items.append(
                CollectedItem(
                    raw_payload=raw_item,
                    external_id=mention.external_id,
                    mention=mention,
                )
            )
        return items
