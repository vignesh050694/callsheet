"""X via tikhub's search timeline — the primary endpoint (E03-S07).

Mapped against a real capture: run `01KZRZKR92DWVPEAYNVP177HP8`, 11 Aug 2026, the anchored
query `Lokesh Kanagaraj DC`, 20 posts for $0.0015 in 4.4 seconds. The response is committed
verbatim at `tests/fixtures/collection/x_tikhub_search_timeline.json`, so this mapping can
be checked against something that actually happened rather than against a guess at the
vendor's documentation.
"""

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from app.core.platforms import Platform
from app.services.collection.adapters.base import EndpointAdapter, ProviderRequest
from app.services.collection.mention_shape import MentionEngagement, NormalizedMention
from app.services.collection.payload_values import (
    clean_post_text,
    optional_int,
    optional_string,
    parse_x_timestamp,
    read_hashtag_texts,
    require_string,
)

# The timeline carries more than posts — the discriminator is what keeps promoted slots and
# user cards out of a corpus that is supposed to be conversation.
_TWEET_ITEM_TYPE = "tweet"

# "Latest" rather than the default "Top": a campaign tracker wants the conversation as it
# happens, and "Top" is the platform's engagement ranking, which over-weights exactly the
# large trade accounts that account-type segmentation exists to separate out (E04-S03).
_SEARCH_TYPE_LATEST = "Latest"


class TikhubXSearchAdapter(EndpointAdapter):
    key: ClassVar[str] = "x.tikhub_search_timeline"
    platform: ClassVar[Platform] = Platform.X
    version: ClassVar[str] = "2026-08-11"

    def build_request(self, query: str, *, page: str | None, limit: int) -> ProviderRequest:
        """PER_CALL, so `limit` is not a cost lever here and the endpoint takes no size.

        The page size is whatever one call returns — 20 in the capture. Passing `limit`
        would suggest a control this endpoint does not offer; the caller caps the result
        list instead, which is the only place the cap can actually be enforced.
        """
        query_params: dict[str, Any] = {
            "keyword": query,
            "search_type": _SEARCH_TYPE_LATEST,
        }
        if page:
            query_params["cursor"] = page
        return ProviderRequest(query_params=query_params)

    def read_items(self, response: Any) -> Sequence[Mapping[str, Any]]:
        if not isinstance(response, Mapping):
            return []
        timeline = response.get("timeline")
        if not isinstance(timeline, list):
            return []
        return [
            item
            for item in timeline
            if isinstance(item, Mapping) and item.get("type") == _TWEET_ITEM_TYPE
        ]

    def read_next_page(self, response: Any) -> str | None:
        if not isinstance(response, Mapping):
            return None
        cursor = response.get("next_cursor")
        return cursor if isinstance(cursor, str) and cursor else None

    def read_external_id(self, item: Mapping[str, Any]) -> str | None:
        return optional_string(item, "tweet_id")

    def to_mention(self, item: Mapping[str, Any]) -> NormalizedMention:
        external_id = require_string(item, "tweet_id")
        handle = require_string(item, "screen_name")
        user_info = item.get("user_info")
        user_info = user_info if isinstance(user_info, Mapping) else {}

        return NormalizedMention(
            platform=Platform.X,
            external_id=external_id,
            text=clean_post_text(require_string(item, "text")),
            posted_at=parse_x_timestamp(item.get("created_at")),
            author_handle=handle,
            # Falls back to the handle rather than to an empty string: a card with a blank
            # name reads as broken, and the handle is the name for plenty of accounts.
            author_display_name=optional_string(user_info, "name") or handle,
            author_follower_count=optional_int(user_info.get("followers_count")),
            # This endpoint returns no permalink, so it is derived. The pair (handle, id)
            # is enough, and both are required fields above.
            permalink=f"https://x.com/{handle}/status/{external_id}",
            platform_reported_language=optional_string(item, "lang"),
            hashtags=read_hashtag_texts(item.get("entities")),
            engagement=MentionEngagement(
                like_count=optional_int(item.get("favorites")),
                reply_count=optional_int(item.get("replies")),
                repost_count=optional_int(item.get("retweets")),
                quote_count=optional_int(item.get("quotes")),
                # A string in this payload — see `optional_int`.
                view_count=optional_int(item.get("views")),
                bookmark_count=optional_int(item.get("bookmarks")),
            ),
        )
