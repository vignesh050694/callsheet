"""Request/response DTOs for titles. These never leak ORM objects to the API."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models.title import (
    POSTER_URL_MAX_LENGTH,
    TITLE_NAME_MAX_LENGTH,
    TITLE_TERM_MAX_LENGTH,
    TitleTermType,
)

MAX_TERMS_PER_FIELD = 50

# `Field(max_length=...)` on a bare `list[str]` bounds the LIST, not the strings in it, so
# the per-item limit has to be annotated on the item type. Without it an over-long term
# reaches a String(300) column and fails as a 500 rather than a 422 — and SQLite, which
# the tests run on, does not enforce VARCHAR limits, so nothing catches it before Postgres.
TermList = list[Annotated[str, Field(max_length=TITLE_TERM_MAX_LENGTH)]]


class TitleCreate(BaseModel):
    """The setup form, field for field.

    Each people field is separate here because that is how a studio thinks about them —
    the service folds them into one identity set on the way in.
    """

    name: str = Field(min_length=1, max_length=TITLE_NAME_MAX_LENGTH)
    aliases: TermList = Field(default_factory=list, max_length=MAX_TERMS_PER_FIELD)
    hashtags: TermList = Field(default_factory=list, max_length=MAX_TERMS_PER_FIELD)
    lead_cast: TermList = Field(default_factory=list, max_length=MAX_TERMS_PER_FIELD)
    directors: TermList = Field(default_factory=list, max_length=MAX_TERMS_PER_FIELD)
    music_directors: TermList = Field(default_factory=list, max_length=MAX_TERMS_PER_FIELD)
    poster_url: str | None = Field(default=None, max_length=POSTER_URL_MAX_LENGTH)


class TitleTermRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    term_type: TitleTermType
    value: str = Field(max_length=TITLE_TERM_MAX_LENGTH)


class TitleRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    poster_url: str | None
    terms: list[TitleTermRead]
    collection_terms: list[str] = Field(
        description=(
            "The normalised identity set collection queries against — the whole set, "
            "never the bare name."
        )
    )
    has_anchor_term: bool
    created_at: datetime
    updated_at: datetime
