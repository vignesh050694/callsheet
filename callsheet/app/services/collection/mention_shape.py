"""The one internal shape every provider's response becomes (E03-S07).

Everything above the collection layer reads this and only this. It carries no trace of who
fetched it: no provider name, no endpoint, no vendor field names. That absence is the
feature — if a mention could say where it came from, a chart could group by it, and the
moment a chart groups by provider a switchover becomes a visible discontinuity in the
product rather than an operational detail. Provenance is kept, but on the raw payload
beside it, reachable by a join and never on the default read path.

What is *not* here matters as much. No sentiment, no account type, no detected language,
no theme — those are E04's, they are derived rather than collected, and a field sitting
here waiting for them would invite someone to fill it in with a guess.
"""

from dataclasses import dataclass, field
from datetime import datetime

from app.core.platforms import Platform


@dataclass(frozen=True, slots=True)
class MentionEngagement:
    """Counts as they stood at collection time.

    A snapshot, deliberately: v1 does not re-fetch these as they drift (E03-S04's out of
    scope). Every field is optional because providers disagree about which they return,
    and a zero we invented is indistinguishable from a zero the platform reported.
    """

    like_count: int | None = None
    reply_count: int | None = None
    repost_count: int | None = None
    quote_count: int | None = None
    view_count: int | None = None
    bookmark_count: int | None = None


@dataclass(frozen=True, slots=True)
class NormalizedMention:
    """One post, in the product's own vocabulary.

    `platform_reported_language` is named for its provenance rather than called
    `language`, and the naming is not pedantry. In the 20-post capture taken for this
    story, X labelled Tamil-script text `et` (Estonian), romanised Tamil `in`, and
    code-mixed Tamil-in-Latin `en` — five of twenty wrong. A field called `language`
    would be filtered on by the first person who saw it, silently dropping half a title's
    regional conversation. Detection is E04-S01's, and it lands in a different field.
    """

    platform: Platform
    external_id: str
    text: str
    posted_at: datetime
    author_handle: str
    author_display_name: str
    author_follower_count: int | None = None
    permalink: str | None = None
    platform_reported_language: str | None = None
    hashtags: list[str] = field(default_factory=list)
    engagement: MentionEngagement = field(default_factory=MentionEngagement)
