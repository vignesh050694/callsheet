"""Which endpoints this application can actually read (E03-S07).

The catalogue in `app.core.collection_endpoints` says what exists and what it costs. This
registry says what can be turned into mentions today. They are separate on purpose: an
endpoint can be known, priced, and configured long before anyone has mapped its payload,
and pretending otherwise would mean a platform quietly collecting nothing.

Only X ships mapped, against both of its providers. Instagram, Reddit and YouTube are
routed in configuration and land here with their own collection stories.
"""

from app.services.collection.adapters.base import EndpointAdapter, ProviderRequest
from app.services.collection.adapters.x_apify import ApifyXTweetScraperAdapter
from app.services.collection.adapters.x_tikhub import TikhubXSearchAdapter

ENDPOINT_ADAPTERS: dict[str, EndpointAdapter] = {
    adapter.key: adapter
    for adapter in (
        TikhubXSearchAdapter(),
        ApifyXTweetScraperAdapter(),
    )
}


def get_adapter(endpoint_key: str) -> EndpointAdapter | None:
    return ENDPOINT_ADAPTERS.get(endpoint_key)


__all__ = [
    "ENDPOINT_ADAPTERS",
    "ApifyXTweetScraperAdapter",
    "EndpointAdapter",
    "ProviderRequest",
    "TikhubXSearchAdapter",
    "get_adapter",
]
