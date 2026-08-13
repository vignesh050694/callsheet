"""What every endpoint adapter must know how to do (E03-S07).

An adapter is the only place a vendor's vocabulary is allowed to exist. It knows two
things nobody else may: how to ask this endpoint for a page, and how to read what comes
back. Everything else in the collection layer speaks platform, query, and page.

Both halves belong together. A registry that mapped endpoints to response parsers but let
the caller build the request would still leak vendor knowledge upward — tikhub takes
`keyword` in the query string and pages on an opaque `cursor`, apify takes `searchTerms`
in a JSON body and pages by asking for more items. The caller cannot know that and stay
provider-agnostic, so the adapter owns the request too.
"""

import abc
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.core.platforms import Platform
from app.services.collection.mention_shape import NormalizedMention
from app.services.collection.source import CollectionWindow


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    """A call, in the three parts Monid's runner takes it in."""

    body: dict[str, Any] = field(default_factory=dict)
    query_params: dict[str, Any] = field(default_factory=dict)
    path_params: dict[str, Any] = field(default_factory=dict)


class EndpointAdapter(abc.ABC):
    """One endpoint's two-way translation."""

    key: ClassVar[str]
    platform: ClassVar[Platform]
    # Bumped when the mapping changes. Stored beside every raw payload so a corpus
    # collected under a wrong mapping can be found and re-read later (E03-S04) instead of
    # being silently trusted.
    version: ClassVar[str]

    @abc.abstractmethod
    def build_request(
        self,
        query: str,
        *,
        page: str | None,
        limit: int,
        window: CollectionWindow | None = None,
    ) -> ProviderRequest:
        """One page of `query`. Never more than one — pagination is the caller's decision.

        `window` is a past date range (E03-S03), and translating it is the second half of
        why request-building lives in the adapter rather than in the caller. The two X
        providers express the identical bound in unrelated places: one as a search operator
        inside the keyword text, the other as two fields in a JSON body. An adapter that
        cannot honour a window must say so by raising, never by ignoring it — silently
        dropping the bound turns a cheap targeted backfill into a full-price poll of the
        present, billed against a range the studio will never see results for.
        """

    @abc.abstractmethod
    def read_items(self, response: Any) -> Sequence[Mapping[str, Any]]:
        """The post-shaped objects in this response, ignoring everything that is not one."""

    @abc.abstractmethod
    def read_next_page(self, response: Any) -> str | None:
        """The cursor for the following page, or None when the provider offers none."""

    @abc.abstractmethod
    def read_external_id(self, item: Mapping[str, Any]) -> str | None:
        """The platform's own id for this item, read on its own.

        Separate from `to_mention` because the two questions fail independently. An item
        whose author handle is missing cannot become a mention, but it still has an id,
        and that id is what stops the same broken payload being stored again on every
        overlapping poll — and what lets it be re-read once the mapping is fixed. Reading
        the id inside `to_mention` would throw both away together.
        """

    @abc.abstractmethod
    def to_mention(self, item: Mapping[str, Any]) -> NormalizedMention:
        """This item as a mention. Raises `PayloadShapeError` if it cannot be read."""
