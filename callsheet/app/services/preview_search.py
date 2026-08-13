"""The search port a title preview runs through (E02-S03).

A preview has to show the studio posts a real platform actually returned, because the
whole point of it is that they can trust the setup before committing to it. The layer
that talks to Monid is E03; this is the seam it plugs into, and the only shape the
preview service depends on.

Two cost rules live in the port rather than in the adapter, because they are what makes
a preview safe to hand out for free (concept note §7, cost-control rule 2):

* **one call, one page.** The adapter must never paginate. On a PER_CALL endpoint cost
  is driven by pagination depth, so a preview that can walk pages is a preview that can
  run away.
* **a hard result cap.** `PREVIEW_POST_LIMIT` is passed on every call and re-applied by
  the service on the way out, so a provider that ignores it cannot widen the sample.

Until an adapter is configured, the default binding refuses and says so. Returning
invented posts would be strictly worse than returning none — a studio that trusts a
fabricated sample gets exactly the junk dashboard this story exists to prevent.
"""

import abc
from dataclasses import dataclass
from datetime import datetime

import structlog

from app.core.exceptions import ServiceUnavailableError

_logger = structlog.get_logger(__name__)

# One page, capped. Matches the live run in the concept note: 20 posts for $0.0015.
PREVIEW_POST_LIMIT = 20

# X only, deliberately. One platform is enough to catch a badly described film, and every
# extra platform multiplies the cost of an action the studio has not paid for yet.
PREVIEW_PLATFORM = "x"

PREVIEW_UNAVAILABLE_MESSAGE = (
    "Live preview is not configured on this deployment yet, so there are no real posts "
    "to show. You can still save the title — collection starts as soon as it exists."
)


@dataclass(frozen=True, slots=True)
class SamplePost:
    """One post as a platform returned it, before anything has been analysed.

    Deliberately thin. A preview is discarded the moment the studio closes it, so this
    carries what a human needs to judge "is this my film?" and nothing the pipeline
    would later want — no sentiment, no account type, no language detection, because
    none of those have run and inventing them here would put unearned confidence on
    screen.

    `platform_reported_language` is named for its provenance on purpose. Roughly half
    the non-English content in the live sample was mislabelled by the platform, so this
    field is a claim, not a fact, and every consumer has to be able to see that from the
    name alone.
    """

    external_id: str
    author_handle: str
    author_display_name: str
    text: str
    posted_at: datetime
    permalink: str | None = None
    platform_reported_language: str | None = None


class PreviewSearch(abc.ABC):
    """One capped search against one platform. No pagination, no persistence."""

    @abc.abstractmethod
    async def search_recent(self, query: str, *, limit: int) -> list[SamplePost]:
        """Returns at most `limit` recent posts for `query`, from a single call."""


class UnconfiguredPreviewSearch(PreviewSearch):
    """The default binding: refuses rather than inventing a sample.

    This is what runs until E03 supplies a real adapter. It fails as an expected,
    typed domain error — a 503 with an explanation the studio can act on — rather than
    as an exception, because "not wired up yet" is a state of the deployment, not a bug
    in the request.
    """

    async def search_recent(self, query: str, *, limit: int) -> list[SamplePost]:
        _logger.warning("title.preview.search_unconfigured", limit=limit)
        raise ServiceUnavailableError(PREVIEW_UNAVAILABLE_MESSAGE)
