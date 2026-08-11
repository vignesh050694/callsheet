"""Request/response DTOs for titles. These never leak ORM objects to the API."""

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.core.release_phase import ReleasePhase
from app.models.title import (
    MILESTONE_NAME_MAX_LENGTH,
    POSTER_URL_MAX_LENGTH,
    TITLE_NAME_MAX_LENGTH,
    TITLE_TERM_MAX_LENGTH,
    TitleTermType,
)

MAX_TERMS_PER_FIELD = 50
MAX_MILESTONES_PER_TITLE = 50

# `Field(max_length=...)` on a bare `list[str]` bounds the LIST, not the strings in it, so
# the per-item limit has to be annotated on the item type. Without it an over-long term
# reaches a String(300) column and fails as a 500 rather than a 422 — and SQLite, which
# the tests run on, does not enforce VARCHAR limits, so nothing catches it before Postgres.
TermList = list[Annotated[str, Field(max_length=TITLE_TERM_MAX_LENGTH)]]


class TitleMilestoneCreate(BaseModel):
    """One campaign beat as the form submits it."""

    name: str = Field(min_length=1, max_length=MILESTONE_NAME_MAX_LENGTH)
    occurs_on: date


class TitleCreate(BaseModel):
    """The setup form, field for field.

    Each people field is separate here because that is how a studio thinks about them —
    the service folds them into one identity set on the way in.
    """

    name: str = Field(min_length=1, max_length=TITLE_NAME_MAX_LENGTH)
    release_date: date = Field(
        description="Required. The boundary every time-series splits on (E02-S02)."
    )
    milestones: list[TitleMilestoneCreate] = Field(
        default_factory=list,
        max_length=MAX_MILESTONES_PER_TITLE,
        description="Optional at setup — they can be added later without touching anything else.",
    )
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


class TitleScheduleUpdate(BaseModel):
    """A replacement schedule: the release date and the whole milestone list.

    Deliberately narrow. It carries no identity terms, so saving a corrected release date
    cannot disturb the identity set collection is already running against — which is the
    story's requirement that milestones can be added later without touching collected data.

    The milestone list replaces rather than appends, because that is what an editable list
    in a form means: removing a row and saving has to remove the milestone.
    """

    release_date: date
    milestones: list[TitleMilestoneCreate] = Field(
        default_factory=list,
        max_length=MAX_MILESTONES_PER_TITLE,
    )


class TitleMilestoneRead(BaseModel):
    id: uuid.UUID
    name: str = Field(max_length=MILESTONE_NAME_MAX_LENGTH)
    occurs_on: date
    phase: ReleasePhase = Field(
        description=(
            "Which side of the release this beat falls on. Derived at read time from the "
            "title's current release date, never stored."
        )
    )


class TitleRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    release_date: date
    milestones: list[TitleMilestoneRead]
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
