"""Request/response DTOs for alias discovery (E02-S04).

The response is built to be *judged*, not skimmed. A candidate on its own is a string the
studio has no reason to trust; with the number of posts carrying it and one of those posts
quoted in full, it is a decision someone can actually make. That is the whole shape of
this file.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.alias_candidates import AliasCandidateKind
from app.models.title import TITLE_TERM_MAX_LENGTH, TitleTermType
from app.schemas.title import TitleTermRead

# Which term kinds a suggestion can be approved into. Deliberately not the whole enum: a
# discovery is a positive claim, so nothing on this screen can create an exclusion — that
# is E02-S05, a different decision made against different evidence. Refused at the request
# schema so it is a 422 naming the field, not a service error naming a rule.
APPROVABLE_TERM_TYPES = frozenset({TitleTermType.ALIAS, TitleTermType.HASHTAG})

NOT_APPROVABLE_MESSAGE = "A discovered term can only be approved as an alias or a hashtag"


class AliasSamplePostRead(BaseModel):
    """One post carrying the candidate, quoted so the term can be judged in context.

    Nothing here has been through the analysis pipeline — no sentiment, no account type,
    no language detection — because none of it has run. Every field is either what the
    platform said or what this request worked out, and the names say which.
    """

    id: uuid.UUID
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


class AliasCandidateRead(BaseModel):
    """One term the corpus uses that this title's identity set does not claim."""

    kind: AliasCandidateKind
    value: str = Field(
        description="The commonest spelling in the corpus — what people actually type."
    )
    normalized_value: str
    mention_count: int = Field(
        description=(
            "How many of the scanned posts carry this term. Unsegmented: account typing "
            "is E04-S03, so trade, distributor and promotional accounts are counted here "
            "alongside audience posts."
        )
    )
    resembles: str | None = Field(
        description=(
            "The declared term this is a near-miss of. Null for hashtags, which are "
            "offered on their own volume rather than on resemblance to anything."
        )
    )
    sample: AliasSamplePostRead | None


class AliasRejectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: AliasCandidateKind
    value: str
    created_at: datetime


class AliasSuggestionsRead(BaseModel):
    """The suggestion screen's payload, with the honesty about its own coverage."""

    candidates: list[AliasCandidateRead]
    rejections: list[AliasRejectionRead] = Field(
        description="Terms already refused for this title. They are never re-suggested."
    )
    scanned_mentions: int = Field(
        description=(
            "How many posts these counts were computed over, newest first. Equal to "
            "`corpus_size` until a campaign outgrows the scan cap; below it after that, "
            "at which point every count here describes the recent window rather than the "
            "whole campaign."
        )
    )
    corpus_size: int = Field(description="Every post this title holds. Unsegmented.")


class AliasApproval(BaseModel):
    """Approving one suggestion into the identity set.

    `term_type` is carried rather than inferred from the candidate list, because the two
    kinds are queried differently — a hashtag runs bare, an alias runs anchored to a
    person — and a studio approving from a list they are reading should be approving the
    thing the list showed them.
    """

    value: str = Field(min_length=1, max_length=TITLE_TERM_MAX_LENGTH)
    term_type: TitleTermType = Field(
        description=(
            "Only `alias` or `hashtag`. A discovery is a positive claim; creating an "
            "exclusion from this screen is a different decision (E02-S05)."
        )
    )

    @field_validator("term_type")
    @classmethod
    def _must_be_a_positive_claim(cls, term_type: TitleTermType) -> TitleTermType:
        if term_type not in APPROVABLE_TERM_TYPES:
            raise ValueError(NOT_APPROVABLE_MESSAGE)
        return term_type


class AliasRejection(BaseModel):
    """Refusing one suggestion, permanently, until it is explicitly restored."""

    value: str = Field(min_length=1, max_length=TITLE_TERM_MAX_LENGTH)
    kind: AliasCandidateKind


class AliasApprovalRead(BaseModel):
    """What approving did — the term, and what it was worth against the stored corpus."""

    term: TitleTermRead
    rematched_mentions: int = Field(
        description=(
            "Posts already collected that carry this term and have now been credited to "
            "it. No provider call was made to find them (E03-S04)."
        )
    )
    scanned_mentions: int = Field(
        description="How many stored posts were checked. The whole corpus, not a window."
    )
    collection_calls: int = Field(
        description="Always zero. Re-matching reads stored posts and cannot spend."
    )
