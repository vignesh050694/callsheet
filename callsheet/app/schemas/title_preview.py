"""Request/response DTOs for the setup preview (E02-S03).

The request is the setup form's identity fields, unsaved. There is no title id here on
purpose: the whole value of the preview is that it happens *before* the studio commits,
so it cannot depend on a row existing.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.title import TITLE_NAME_MAX_LENGTH
from app.schemas.title import MAX_TERMS_PER_FIELD, TermList


class TitlePreviewRequest(BaseModel):
    """The identity set as the form currently holds it, before anything is saved."""

    name: str = Field(min_length=1, max_length=TITLE_NAME_MAX_LENGTH)
    aliases: TermList = Field(default_factory=list, max_length=MAX_TERMS_PER_FIELD)
    hashtags: TermList = Field(default_factory=list, max_length=MAX_TERMS_PER_FIELD)
    lead_cast: TermList = Field(default_factory=list, max_length=MAX_TERMS_PER_FIELD)
    directors: TermList = Field(default_factory=list, max_length=MAX_TERMS_PER_FIELD)
    music_directors: TermList = Field(default_factory=list, max_length=MAX_TERMS_PER_FIELD)


class PreviewPostRead(BaseModel):
    """One sampled post, with the evidence a human needs to judge it.

    Nothing here has been through the analysis pipeline — no sentiment, no account type,
    no language detection — because none of it has run. Every field is either what the
    platform said or what this request worked out from the identity set, and the names
    say which.
    """

    id: str
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
    matched_terms: list[str] = Field(
        description="Identity terms found in this post — why it is in the sample."
    )
    candidate_exclusion_terms: list[str] = Field(
        description=(
            "Hashtags in this post that the identity set does not claim. If the owner "
            "marks the post 'not my title', one of these is what dragged it in."
        )
    )


class TitlePreviewRead(BaseModel):
    """A discarded sample. Nothing in this response is stored — collection starts at E03-S01."""

    platform: str
    query: str = Field(description="The single anchored query this sample came from.")
    post_limit: int = Field(description="The hard cap on the sample, applied per request.")
    posts: list[PreviewPostRead]
