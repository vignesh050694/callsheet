"""Telling data ops a platform has stopped reporting (E03-S05).

The story's Notes ask for one thing this layer does not otherwise do: "repeated failures
should raise an internal alert to data ops **before the customer notices**". Everything else
in this story is a dashboard — it tells a studio what is already true. This is the half that
tries to make it stop being true first.

A seam rather than an integration, on the same reasoning as `SpendPolicy`: the destination
is somebody's paging setup and belongs to E08's alerting work, but a failure path that has
no way to raise an alert can never be made to raise one, and retrofitting the call site into
a worker loop later is how "we alert on this" becomes a code review convention.

The default binding logs at **error** with the platform, the title, and the consecutive
failure count. Deliberately not `warning`: a single failed poll already logs at warning, and
if the thing that means "this has failed six times running and a customer is about to see a
flat line" is indistinguishable in a log stream from the thing that means "one poll was
refused", the alert has no signal in it.

Repeated, not first. One failed poll is a blip — a dropped connection, a provider hiccup —
and paging on it is how an on-call rotation learns to filter this alert out entirely.
"""

import abc
import uuid

import structlog

from app.core.platforms import Platform

_logger = structlog.get_logger(__name__)


class CollectionHealthAlerter(abc.ABC):
    @abc.abstractmethod
    async def platform_repeatedly_failing(
        self,
        *,
        title_id: uuid.UUID,
        platform: Platform,
        consecutive_failures: int,
        reason: str | None,
    ) -> None:
        """Raised when a platform crosses the repeated-failure threshold for a title."""


class LoggingCollectionHealthAlerter(CollectionHealthAlerter):
    """The default binding: a structured error line, which is what data ops watch today.

    Not silent, and not a no-op. An unrouted alerter that quietly discarded these would make
    a deployment with no alerting look exactly like one whose platforms are all healthy —
    the same confusion `UnrestrictedSpendPolicy` refuses to create.
    """

    async def platform_repeatedly_failing(
        self,
        *,
        title_id: uuid.UUID,
        platform: Platform,
        consecutive_failures: int,
        reason: str | None,
    ) -> None:
        _logger.error(
            "collection.health.platform_repeatedly_failing",
            title_id=str(title_id),
            platform=str(platform),
            consecutive_failures=consecutive_failures,
            reason=reason,
        )
