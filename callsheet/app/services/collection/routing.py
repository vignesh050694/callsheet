"""Turning "collect X" into "call this endpoint" (E03-S07).

The whole of the switchover lives here. A caller names a platform; this decides which
endpoint serves it, and refuses clearly when the answer is not usable. Refusing loudly
matters more than it looks: a platform pointed at an endpoint nobody has mapped would
otherwise poll on schedule, return nothing, and look exactly like a title with no
conversation.
"""

import structlog

from app.core.collection_endpoints import EndpointDescriptor, get_endpoint
from app.core.config import Settings
from app.core.exceptions import ServiceUnavailableError
from app.core.platforms import Platform
from app.services.collection.adapters import EndpointAdapter, get_adapter

_logger = structlog.get_logger(__name__)

NO_ROUTE_MESSAGE = "No collection endpoint is configured for {platform}"
UNKNOWN_ENDPOINT_MESSAGE = "Collection endpoint {key!r} is not in the catalogue"
WRONG_PLATFORM_MESSAGE = "Collection endpoint {key!r} serves {actual}, not {expected}"
NO_ADAPTER_MESSAGE = (
    "Collection endpoint {key!r} is configured for {platform} but nothing can read its "
    "responses yet, so collecting through it would store nothing"
)


class CollectionRoute:
    """A resolved platform → endpoint → adapter chain, and how it charges."""

    def __init__(self, endpoint: EndpointDescriptor, adapter: EndpointAdapter) -> None:
        self.endpoint = endpoint
        self.adapter = adapter

    @property
    def platform(self) -> Platform:
        return self.endpoint.platform


def resolve_route(platform: Platform, settings: Settings) -> CollectionRoute:
    """The endpoint this platform is currently pointed at.

    Validates the configuration rather than trusting it, because the value being read is
    one somebody typed into an environment variable during an outage. A key that names a
    different platform's endpoint is the mistake worth catching hardest — it would collect
    real posts about the wrong thing, which reads as a data problem rather than a
    configuration one.
    """
    configured = settings.collection_endpoints.get(platform)
    if configured is None or not configured.active_key:
        _logger.error("collection.route.unconfigured", platform=str(platform))
        raise ServiceUnavailableError(NO_ROUTE_MESSAGE.format(platform=platform))

    endpoint_key = configured.active_key
    endpoint = get_endpoint(endpoint_key)
    if endpoint is None:
        _logger.error(
            "collection.route.unknown_endpoint", platform=str(platform), endpoint=endpoint_key
        )
        raise ServiceUnavailableError(UNKNOWN_ENDPOINT_MESSAGE.format(key=endpoint_key))

    if endpoint.platform is not platform:
        _logger.error(
            "collection.route.platform_mismatch",
            platform=str(platform),
            endpoint=endpoint_key,
            endpoint_platform=str(endpoint.platform),
        )
        raise ServiceUnavailableError(
            WRONG_PLATFORM_MESSAGE.format(
                key=endpoint_key, actual=endpoint.platform, expected=platform
            )
        )

    adapter = get_adapter(endpoint_key)
    if adapter is None:
        _logger.error(
            "collection.route.no_adapter", platform=str(platform), endpoint=endpoint_key
        )
        raise ServiceUnavailableError(
            NO_ADAPTER_MESSAGE.format(key=endpoint_key, platform=platform)
        )

    _logger.debug(
        "collection.route.resolved",
        platform=str(platform),
        endpoint=endpoint_key,
        provider=endpoint.provider,
        price_model=str(endpoint.price_model),
    )
    return CollectionRoute(endpoint=endpoint, adapter=adapter)
