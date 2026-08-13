"""Request/response DTOs for the mentions feed and exclusion rules (E02-S05).

The impact response is the important one. A studio confirms a *number*, not a string —
`#DC` and `#DareDevil` are indistinguishable as text and remove wildly different amounts of
a title's corpus, and the story makes showing that difference a precondition of the action.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.title import TITLE_TERM_MAX_LENGTH
from app.schemas.title import TitleTermRead

MAX_FEED_PAGE_SIZE = 100


class MentionRead(BaseModel):
    """One collected post, with the evidence for judging whether it belongs here.

    Nothing here has been through the analysis pipeline — no sentiment, no account type,
    no language detection — because none of it has run. Every field is either what the
    platform said or what this request worked out from the identity set, and the names say
    which.
    """

    id: uuid.UUID
    platform: str
    author_handle: str
    author_display_name: str
    text: str
    posted_at: datetime
    permalink: str | None
    platform_reported_language: str | None = Field(
        description=(
            "The platform's own language tag, unverified. It was wrong on roughly half "
            "the non-English content in the live sample, so it is shown as a claim and "
            "never used to filter."
        )
    )
    hashtags: list[str]
    matched_terms: list[str] = Field(
        description="Identity terms found in this post — why it was collected for this title."
    )
    candidate_exclusion_terms: list[str] = Field(
        description=(
            "Hashtags in this post that the identity set does not claim. If the owner "
            "marks it 'not my title', one of these is what dragged it in."
        )
    )
    excluded_by_term: str | None = Field(
        description="The exclusion rule that disowned this post, or null if it counts."
    )
    excluded_at: datetime | None


class MentionFeedRead(BaseModel):
    items: list[MentionRead]
    counted_total: int = Field(
        description=(
            "Posts that count towards this title. Unsegmented: account typing is E04-S03, "
            "so trade, distributor and promotional accounts are in this number."
        )
    )
    collected_total: int = Field(
        description=(
            "Every post collected, disowned ones included. The gap between this and "
            "`counted_total` is exactly what this title's exclusion rules removed."
        )
    )
    limit: int
    offset: int


class ExclusionCreate(BaseModel):
    """One term to disqualify posts from this title."""

    value: str = Field(min_length=1, max_length=TITLE_TERM_MAX_LENGTH)


class ExclusionImpactRead(BaseModel):
    """What the rule would do, measured before it is made."""

    value: str
    normalized_value: str
    would_remove: int = Field(
        description=(
            "Counted posts already collected that this rule would remove. Measured over "
            "the whole corpus, not a sample."
        )
    )
    counted_now: int = Field(description="Posts counting towards this title before the rule.")
    removes_everything: bool = Field(
        description=(
            "True when the rule would remove every post this title has. Almost always a "
            "mis-click — the studio's own name or a term their whole corpus carries."
        )
    )
    is_already_excluded: bool
    samples: list[MentionRead] = Field(
        description="A few of the posts it would remove. A count alone is not reviewable."
    )


class ExclusionRead(BaseModel):
    id: uuid.UUID
    value: str
    normalized_value: str


class ExclusionCreatedRead(BaseModel):
    term: TitleTermRead
    removed_mentions: int = Field(
        description=(
            "Already-collected posts this rule removed from every count and chart. Nothing "
            "was deleted and nothing was re-collected — the posts are marked, not dropped."
        )
    )


class ExclusionRemovedRead(BaseModel):
    value: str
    restored_mentions: int = Field(
        description=(
            "Posts given back to the counts. Fewer than the rule removed when a post also "
            "carries another excluded term — that one keeps it out."
        )
    )
