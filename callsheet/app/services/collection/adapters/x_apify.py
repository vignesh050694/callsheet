"""X via apify's tweet scraper — the alternative endpoint (E03-S07).

The story's scenario in code: same platform, different vendor, same mentions out. Mapped
against run `01KZRZRT9ZK7XFXM457ZWJXFFY`, taken minutes after the tikhub capture with the
same query, and committed at `tests/fixtures/collection/x_apify_tweet_scraper.json`.

The two captures overlap on tweet `2087233047506866356`, which is the point. Through this
adapter and through `TikhubXSearchAdapter` that post normalises to the same
`external_id`, the same author, and the same text, so a title collected through one
provider and then the other has one continuous series rather than a duplicate and a seam.
Its view count differs between the captures (87 against 93, ten minutes apart) — that is
the snapshot-at-collection model working, not a mismatch.

This endpoint is billed PER_RESULT, unlike the primary. The result cap is therefore not a
tidiness measure here, it is the bill, and `maxItems` is the only thing standing between a
poll and an unbounded charge (concept note §7 rule 3).
"""

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from app.core.platforms import Platform
from app.services.collection.adapters.base import EndpointAdapter, ProviderRequest
from app.services.collection.mention_shape import MentionEngagement, NormalizedMention
from app.services.collection.payload_values import (
    clean_post_text,
    longest_text,
    optional_int,
    optional_string,
    parse_x_timestamp,
    read_hashtag_texts,
    require_string,
)
from app.services.collection.source import CollectionWindow

_TWEET_ITEM_TYPE = "tweet"
_SORT_LATEST = "Latest"


class ApifyXTweetScraperAdapter(EndpointAdapter):
    key: ClassVar[str] = "x.apify_tweet_scraper"
    platform: ClassVar[Platform] = Platform.X
    version: ClassVar[str] = "2026-08-11"

    def build_request(
        self,
        query: str,
        *,
        page: str | None,
        limit: int,
        window: CollectionWindow | None = None,
    ) -> ProviderRequest:
        """`maxItems` is the cap, and on a PER_RESULT endpoint it is also the price.

        This actor has no cursor. `page` is accepted to satisfy the port and ignored,
        because asking it for "the next page" would mean asking for a larger result set
        and paying for the first page again — which is not what the caller means.

        A window becomes `start`/`end`, two body fields rather than the search operators the
        primary endpoint needs (E03-S03). The actor documents both as calendar days, and it
        treats `end` as exclusive exactly as X's `until:` does, so the same rounding rule
        applies and is applied in the same direction: over-ask by a fraction of a day rather
        than lose the day a range ends on.
        """
        body: dict[str, Any] = {
            "searchTerms": [query],
            "maxItems": limit,
            "sort": _SORT_LATEST,
        }
        if window is not None:
            body["start"] = window.start_day.isoformat()
            body["end"] = window.exclusive_end_day.isoformat()
        return ProviderRequest(body=body)

    def read_items(self, response: Any) -> Sequence[Mapping[str, Any]]:
        """The response is a bare list of records, not an envelope."""
        if not isinstance(response, list):
            return []
        return [
            item
            for item in response
            if isinstance(item, Mapping) and item.get("type") == _TWEET_ITEM_TYPE
        ]

    def read_next_page(self, response: Any) -> str | None:
        return None

    def read_external_id(self, item: Mapping[str, Any]) -> str | None:
        return optional_string(item, "id")

    def to_mention(self, item: Mapping[str, Any]) -> NormalizedMention:
        author = item.get("author")
        author = author if isinstance(author, Mapping) else {}
        handle = require_string(author, "userName")

        return NormalizedMention(
            platform=Platform.X,
            external_id=require_string(item, "id"),
            # Both fields exist and either one can be the truncated one — see `longest_text`.
            text=clean_post_text(longest_text(item.get("text"), item.get("fullText"))),
            posted_at=parse_x_timestamp(item.get("createdAt")),
            author_handle=handle,
            author_display_name=optional_string(author, "name") or handle,
            author_follower_count=optional_int(author.get("followers")),
            # Unlike tikhub, this provider returns the canonical URL. Preferred over
            # deriving one so a handle change between collection and reading still
            # resolves.
            permalink=optional_string(item, "url", "twitterUrl"),
            platform_reported_language=optional_string(item, "lang"),
            hashtags=read_hashtag_texts(item.get("entities")),
            engagement=MentionEngagement(
                like_count=optional_int(item.get("likeCount")),
                reply_count=optional_int(item.get("replyCount")),
                repost_count=optional_int(item.get("retweetCount")),
                quote_count=optional_int(item.get("quoteCount")),
                view_count=optional_int(item.get("viewCount")),
                bookmark_count=optional_int(item.get("bookmarkCount")),
            ),
        )
