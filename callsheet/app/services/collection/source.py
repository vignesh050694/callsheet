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
from datetime import date, datetime, time, timedelta
from typing import Any

import structlog

from app.core.collection_endpoints import EndpointDescriptor
from app.core.exceptions import ServiceUnavailableError
from app.core.platforms import Platform
from app.core.timestamps import as_utc
from app.services.collection.mention_shape import NormalizedMention

_logger = structlog.get_logger(__name__)

COLLECTION_UNAVAILABLE_MESSAGE = (
    "Collection is not configured on this deployment, so no platform can be polled yet."
)


@dataclass(frozen=True, slots=True)
class CollectionWindow:
    """The stretch of past conversation a call is asking for (E03-S03).

    The port speaks two instants. It does not speak `since:`, `until:`, `start`, `end`, or
    any other operator — those are vendor vocabulary and belong in an adapter, which is the
    whole of E03-S07's rule. tikhub takes the bound as a search operator inside the keyword
    string; apify takes it as two fields in a JSON body. Neither shape can travel upward.

    Half-open, `posted_from` inclusive and `posted_until` exclusive, so two adjacent windows
    tile without asking for the same day twice — the same convention
    `count_for_title_posted_between` already uses.

    A window is a request, not a filter. Providers honour date bounds approximately and at
    day resolution, so a page may come back carrying posts either side of it. Those posts
    are stored like any other: they were paid for, they are about the title, and discarding
    a paid-for payload is precisely what E03-S04 exists to prevent.

    **Both bounds are normalised to UTC-aware on construction**, and that is load-bearing
    rather than tidy. A window is built from two columns read back off a stored row, and
    SQLite hands those back naive while adapters produce aware datetimes — so every
    comparison between the two raises `TypeError` from inside a walk that has already paid
    for a page. Normalising at the boundary is what makes both places that compare against a
    window correct by construction instead of each remembering. The same trap cost E03-S04 a
    round; `app.core.timestamps` exists because of it.
    """

    posted_from: datetime
    posted_until: datetime

    def __post_init__(self) -> None:
        # `object.__setattr__` because the dataclass is frozen and this is the one place
        # allowed to establish its invariant.
        object.__setattr__(self, "posted_from", as_utc(self.posted_from))
        object.__setattr__(self, "posted_until", as_utc(self.posted_until))
        if self.posted_until <= self.posted_from:
            raise ValueError("A collection window cannot end before it begins")

    @property
    def start_day(self) -> date:
        return self.posted_from.date()

    @property
    def exclusive_end_day(self) -> date:
        """`posted_until` as a whole day, rounded up, for providers that work in days.

        Every date-bounded search this product can reach takes calendar days and treats the
        end as exclusive. Rounding up rather than truncating is what stops the final day of
        a range disappearing: a window ending at 14:00 today truncates to "up to but not
        including today", which silently drops today — and "up to now" is the commonest
        range anyone will ask for.

        Lives on the window rather than in each adapter because it is the same rule for both
        X providers and would otherwise be two copies that can disagree about which way to
        round. What stays vendor-specific is *where the day goes* — a search operator inside
        the keyword for one, a body field for the other.
        """
        if self.posted_until.time() == time(0, 0):
            return self.posted_until.date()
        return self.posted_until.date() + timedelta(days=1)


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
        window: CollectionWindow | None = None,
    ) -> CollectionPage:
        """Fetches a single page. `limit` is a hard cap, not a hint.

        `window` narrows the call to a past date range (E03-S03). Omitted, the call asks for
        the conversation as it stands, which is what every scheduled poll wants. It is a
        parameter of the *request* rather than a filter applied afterwards, because the
        alternative — paging back through the present until the dates match — would mean
        paying for every page between now and a trailer launch six weeks ago.
        """


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
        window: CollectionWindow | None = None,
    ) -> CollectionPage:
        _logger.warning("collection.source.unconfigured", platform=str(platform), limit=limit)
        raise ServiceUnavailableError(COLLECTION_UNAVAILABLE_MESSAGE)
