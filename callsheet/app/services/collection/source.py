"""The collection port: platform + query + page in, mentions out (E03-S07).

This is the interface the concept note's risk #5 asks for. Above it nothing knows that
Monid exists, that tikhub and apify are different companies, or that one of them charges
by the result. Below it, one adapter per endpoint holds all of that.

The port returns each item in both forms at once — normalised *and* raw — because storing
one without the other is what makes a corpus un-reprocessable. An item that could not be
read still comes back, carrying its error, so a mapping mistake costs a re-read later
rather than the post itself (E03-S04).
"""

import abc
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.core.collection_endpoints import EndpointDescriptor
from app.core.exceptions import ServiceUnavailableError
from app.core.platforms import Platform
from app.services.collection.mention_shape import NormalizedMention

_logger = structlog.get_logger(__name__)

COLLECTION_UNAVAILABLE_MESSAGE = (
    "Collection is not configured on this deployment, so no platform can be polled yet."
)


@dataclass(frozen=True, slots=True)
class CollectedItem:
    """One item from a provider, in both forms.

    `mention` is None exactly when `normalization_error` is set. The raw payload is
    present either way — it is the thing that was paid for, and the only thing that
    cannot be recomputed.

    `external_id` is read on its own rather than taken from the mention, so it survives a
    normalisation failure. Without that, an item this adapter cannot read has no identity,
    and an item with no identity cannot be recognised on the next overlapping poll — it
    would be stored again every cycle, forever.
    """

    raw_payload: Mapping[str, Any]
    external_id: str | None = None
    mention: NormalizedMention | None = None
    normalization_error: str | None = None

    @property
    def is_readable(self) -> bool:
        return self.mention is not None


@dataclass(frozen=True, slots=True)
class CollectionPage:
    """One page from one endpoint, with the provenance the caller needs to record it."""

    platform: Platform
    endpoint: EndpointDescriptor
    adapter_version: str
    items: list[CollectedItem] = field(default_factory=list)
    next_page: str | None = None

    @property
    def readable_items(self) -> list[CollectedItem]:
        return [item for item in self.items if item.is_readable]


class CollectionSource(abc.ABC):
    """One page of one platform's conversation. No persistence, no pagination."""

    @abc.abstractmethod
    async def fetch(
        self,
        platform: Platform,
        query: str,
        *,
        page: str | None = None,
        limit: int,
    ) -> CollectionPage:
        """Fetches a single page. `limit` is a hard cap, not a hint."""


class UnconfiguredCollectionSource(CollectionSource):
    """The default binding, until a transport is wired up.

    Same posture as the preview's unconfigured search (E02-S03): a typed 503 saying what
    is missing, never an empty page. An empty page is indistinguishable from "nobody is
    talking about this film", which is the one wrong answer a collection layer must never
    give.
    """

    async def fetch(
        self,
        platform: Platform,
        query: str,
        *,
        page: str | None = None,
        limit: int,
    ) -> CollectionPage:
        _logger.warning("collection.source.unconfigured", platform=str(platform), limit=limit)
        raise ServiceUnavailableError(COLLECTION_UNAVAILABLE_MESSAGE)
