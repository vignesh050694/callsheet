"""The catalogue of collection endpoints, and which one a platform is pointed at (E03-S07).

Risk #5 in the concept note is that Monid is a single dependency for the whole collection
layer. This module is the mitigation: every vendor path the product knows about is written
down *here*, once, behind an internal key. Nothing upstream — not the service, not the
repository, not a dashboard — may name a vendor path, so replacing one is an edit to
configuration rather than a change to the pipeline.

Two facts about an endpoint have to travel with it, because they are what makes swapping
providers a decision rather than a coin toss:

* **who serves it**, so a provider outage can be reasoned about per platform; and
* **how it charges**, because the primary and the alternative do not always agree. X's
  primary is PER_CALL at $0.0015 — cost driven by pagination depth. Its alternative is
  PER_RESULT at $0.0006 — cost driven by how many results come back. Switching X therefore
  changes the *shape* of the bill, not just the amount, and a caller that ignores that can
  turn a fixed-cost poll into an unbounded one (concept note §7, rules 2 and 3).

Prices are the ones `monid_inspect` returned on 11 Aug 2026. They are recorded so the
switchover decision is legible; enforcing spend limits against them is E09's job, not this
module's.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.core.platforms import Platform


class PriceModel(StrEnum):
    """What a call is billed against.

    The distinction is load-bearing. On PER_CALL the only lever is how many calls and how
    deep they paginate. On PER_RESULT the result count *is* the bill, so a call with no
    cap is a call with no ceiling.
    """

    PER_CALL = "per_call"
    PER_RESULT = "per_result"

    @property
    def is_billed_per_result(self) -> bool:
        return self is PriceModel.PER_RESULT


@dataclass(frozen=True, slots=True)
class EndpointDescriptor:
    """One vendor endpoint, named by an internal key rather than by its path.

    `key` is what configuration and logs refer to. `provider` and `path` are the only
    vendor-shaped strings in the application, and they exist here so that everywhere else
    can avoid them.
    """

    key: str
    platform: Platform
    provider: str
    path: str
    price_model: PriceModel
    unit_price_usd: float
    flat_fee_usd: float = 0.0

    @property
    def requires_result_cap(self) -> bool:
        """PER_RESULT without a cap is the runaway risk named in concept note §7 rule 3."""
        return self.price_model.is_billed_per_result


# Verified live via `monid_discover` / `monid_inspect`. Presence here means the endpoint
# exists and is priced — not that this application can read its payload yet. Whether a
# response can be turned into mentions is a separate question, answered by the adapter
# registry in `app.services.collection.adapters`, and asked at resolution time so a
# misconfiguration fails loudly instead of collecting nothing.
ENDPOINT_CATALOG: dict[str, EndpointDescriptor] = {
    endpoint.key: endpoint
    for endpoint in (
        EndpointDescriptor(
            key="x.tikhub_search_timeline",
            platform=Platform.X,
            provider="tikhub",
            path="/api/v1/twitter/web/fetch_search_timeline",
            price_model=PriceModel.PER_CALL,
            unit_price_usd=0.0015,
        ),
        EndpointDescriptor(
            key="x.apify_tweet_scraper",
            platform=Platform.X,
            provider="apify",
            path="/apidojo/tweet-scraper",
            price_model=PriceModel.PER_RESULT,
            unit_price_usd=0.0006,
        ),
        EndpointDescriptor(
            key="instagram.tikhub_hashtag_search",
            platform=Platform.INSTAGRAM,
            provider="tikhub",
            path="/api/v1/instagram/v2/search_hashtags",
            price_model=PriceModel.PER_CALL,
            unit_price_usd=0.003,
        ),
        EndpointDescriptor(
            key="instagram.apify_hashtag_scraper",
            platform=Platform.INSTAGRAM,
            provider="apify",
            path="/apify/instagram-hashtag-scraper",
            price_model=PriceModel.PER_CALL,
            unit_price_usd=0.00345,
        ),
        EndpointDescriptor(
            key="reddit.tikhub_dynamic_search",
            platform=Platform.REDDIT,
            provider="tikhub",
            path="/api/v1/reddit/app/fetch_dynamic_search",
            price_model=PriceModel.PER_CALL,
            unit_price_usd=0.0015,
        ),
        EndpointDescriptor(
            key="reddit.apify_scraper_lite",
            platform=Platform.REDDIT,
            provider="apify",
            path="/trudax/reddit-scraper-lite",
            price_model=PriceModel.PER_RESULT,
            unit_price_usd=0.0057,
            flat_fee_usd=0.02,
        ),
        EndpointDescriptor(
            key="youtube.tikhub_video_comments",
            platform=Platform.YOUTUBE,
            provider="tikhub",
            path="/api/v1/youtube/web_v2/get_video_comments",
            price_model=PriceModel.PER_CALL,
            unit_price_usd=0.0015,
        ),
        EndpointDescriptor(
            key="youtube.apify_comments_scraper",
            platform=Platform.YOUTUBE,
            provider="apify",
            path="/streamers/youtube-comments-scraper",
            price_model=PriceModel.PER_RESULT,
            unit_price_usd=0.00225,
        ),
    )
}


def get_endpoint(key: str) -> EndpointDescriptor | None:
    return ENDPOINT_CATALOG.get(key)


def endpoint_keys_for_platform(platform: Platform) -> list[str]:
    """Every endpoint that could serve this platform — what a switchover may choose from."""
    return [
        endpoint.key
        for endpoint in ENDPOINT_CATALOG.values()
        if endpoint.platform is platform
    ]
