"""The setup preview, served through the collection port (E02-S03 plugged into E03-S07).

E02-S03 defined `PreviewSearch` as a seam and said plainly that the layer which talks to
Monid is E03's. This is that layer plugging in: the preview stops having a search path of
its own and borrows the one collection already polls with.

**Sharing it is the point, not an economy.** A preview drawn from anywhere other than the
endpoint collection actually uses would be a preview of a different product — the studio
approves a sample gathered one way and then gets a dashboard filled another, and the
mismatch surfaces a day later as "this isn't what you showed me". Same routing, same
adapter, same cap, same normalisation.

Both of the port's cost rules survive the trip. **One call, one page**: `page=None` and no
loop, so a preview cannot paginate and therefore cannot run away on a PER_CALL endpoint
(concept note §7 rule 2). **The cap is passed down**, and `TitlePreviewService` re-applies
it on the way out, because neither this class nor the port can enforce what a provider
chooses to return.
"""

import structlog

from app.core.platforms import Platform
from app.services.collection.mention_shape import NormalizedMention
from app.services.collection.source import CollectionSource
from app.services.preview_search import PREVIEW_PLATFORM, PreviewSearch, SamplePost

_logger = structlog.get_logger(__name__)

# Derived from the port's own constant rather than written out again, so "the preview
# searches X" stays one fact. A platform added to the preview later changes it in one file.
_PREVIEW_PLATFORM = Platform(PREVIEW_PLATFORM)


class CollectionSourcePreviewSearch(PreviewSearch):
    """A preview sample, read off one page from the live collection source."""

    def __init__(self, source: CollectionSource) -> None:
        self._source = source

    async def search_recent(self, query: str, *, limit: int) -> list[SamplePost]:
        page = await self._source.fetch(_PREVIEW_PLATFORM, query, page=None, limit=limit)

        posts = [_to_sample_post(item.mention) for item in page.items if item.mention is not None]

        unreadable = len(page.items) - len(posts)
        if unreadable:
            # Warning rather than error: the sample is still usable and the studio is not
            # the person who can fix a mapping. It is worth a line because a preview is
            # often the first place a broken adapter shows itself, and a quietly short
            # sample looks like a quiet film.
            _logger.warning(
                "title.preview.unreadable_items",
                endpoint=page.endpoint.key,
                adapter_version=page.adapter_version,
                unreadable=unreadable,
                fetched=len(page.items),
            )
        return posts


def _to_sample_post(mention: NormalizedMention) -> SamplePost:
    """The corpus shape narrowed to what a human needs to answer "is this my film?".

    Engagement counts, hashtags and follower counts are all present upstream and all
    dropped here. A preview is discarded the moment it is closed, and every extra number
    on it is one more thing inviting a reader to judge the sample by something other than
    reading it.
    """
    return SamplePost(
        external_id=mention.external_id,
        author_handle=mention.author_handle,
        author_display_name=mention.author_display_name,
        text=mention.text,
        posted_at=mention.posted_at,
        permalink=mention.permalink,
        # Carried under its provenance name the whole way. Roughly a quarter of the live
        # capture was mislabelled by X, so this is a claim the screen must be able to
        # present as a claim.
        platform_reported_language=mention.platform_reported_language,
    )
