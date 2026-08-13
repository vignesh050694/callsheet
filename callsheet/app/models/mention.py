"""Collected mentions, and the raw payloads they were read from (E03-S07).

Two tables, because they answer two different questions and have two different lifetimes.

`mentions` is the corpus everything reads: one row per post per title, in the product's
own vocabulary, with no vendor field names and — deliberately — no provider column. A
mention cannot say who fetched it, so nothing downstream can accidentally split a title's
trend at the moment operations changed endpoints.

`mention_raw_payloads` is what was actually paid for. It keeps the provider's response for
an item exactly as it arrived, plus the provenance the normalised row refuses to carry:
which provider, which endpoint, which version of the mapping read it. That is what makes
the corpus reprocessable rather than merely stored (E03-S04), and it is also where a
provider-specific problem is investigated — reachable by a join, off the read path.

Derived fields (language detection, account type, sentiment, themes) are in neither table.
They are E04's, they are versioned separately, and mixing them in here would mean a model
upgrade rewriting the record of what the platform said.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.platforms import Platform
from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin
from app.models.title import Title

EXTERNAL_ID_MAX_LENGTH = 128
HANDLE_MAX_LENGTH = 255
DISPLAY_NAME_MAX_LENGTH = 255
PERMALINK_MAX_LENGTH = 2048
# BCP 47 allows long tags; platforms emit short ones ("en", "te", and the deprecated "in").
LANGUAGE_CODE_MAX_LENGTH = 35
ENDPOINT_KEY_MAX_LENGTH = 120
PROVIDER_MAX_LENGTH = 60
ADAPTER_VERSION_MAX_LENGTH = 40
NORMALIZATION_ERROR_MAX_LENGTH = 500


class Mention(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "mentions"
    __table_args__ = (
        # The same post collected twice is one mention. This is integrity, not the
        # semantic deduplication of reposts and cross-platform repeats, which is E03-S06.
        UniqueConstraint(
            "title_id",
            "platform",
            "external_id",
            name="uq_mention_title_platform_external_id",
        ),
        # Every read of this table is "this title, this window" — a time series is the
        # only shape the product displays.
        Index("ix_mention_title_posted_at", "title_id", "posted_at"),
    )

    title_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("titles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[Platform] = mapped_column(
        SqlEnum(Platform, name="platform", native_enum=False),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(String(EXTERNAL_ID_MAX_LENGTH), nullable=False)
    permalink: Mapped[str | None] = mapped_column(String(PERMALINK_MAX_LENGTH), nullable=True)

    author_handle: Mapped[str] = mapped_column(String(HANDLE_MAX_LENGTH), nullable=False)
    author_display_name: Mapped[str] = mapped_column(
        String(DISPLAY_NAME_MAX_LENGTH), nullable=False
    )
    author_follower_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    text: Mapped[str] = mapped_column(Text, nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Named for its provenance, and never to be used as a filter. In the capture this
    # mapping was written against, X labelled Tamil script "et" and romanised Tamil "in".
    # Detected language is a separate, later field (E04-S01).
    platform_reported_language: Mapped[str | None] = mapped_column(
        String(LANGUAGE_CODE_MAX_LENGTH), nullable=True
    )

    # As the platform tagged them, case preserved: `#DCMovie` and `#dcmovie` both occur,
    # and alias discovery (E02-S04) ranks what people actually typed.
    hashtags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    like_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reply_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    repost_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quote_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    view_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bookmark_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Collected by a historical backfill rather than by a scheduled poll (E03-S03).
    #
    # The one thing a mention is allowed to say about how it arrived, and it is here for the
    # opposite reason there is no provider column. A provider split would be a distinction
    # the reader must never draw; this one they must: platform search depth means a
    # backfilled stretch is a *sample* of what was said, not the record of it, so a chart
    # covering it has to be able to label the gap rather than present it as equivalent
    # (concept note §6.4). First capture wins, as everywhere else in this table — a post
    # already held from a live poll stays live, because that is when it was seen.
    is_backfilled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    title: Mapped[Title] = relationship(lazy="raise")

    def __repr__(self) -> str:
        return f"<Mention {self.platform}:{self.external_id} @{self.author_handle}>"


class MentionRawPayload(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """One provider response item, verbatim, with who said it and how it was read.

    `mention_id` is nullable because an item that could not be normalised is exactly the
    item most worth keeping: it was paid for, it is evidence of a mapping that needs
    fixing, and once fixed it can be re-read into a mention without another call.
    """

    __tablename__ = "mention_raw_payloads"
    __table_args__ = (
        # One payload per post per title. Re-seeing a post on a later poll is not a second
        # payload — v1 is snapshot-at-collection, so the first capture is the record and
        # re-fetching engagement drift is explicitly out of scope (E03-S04).
        UniqueConstraint(
            "title_id",
            "platform",
            "external_id",
            name="uq_mention_raw_payload_title_platform_external_id",
        ),
        Index("ix_mention_raw_payload_endpoint", "endpoint_key", "collected_at"),
    )

    title_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("titles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mention_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mentions.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
    )
    platform: Mapped[Platform] = mapped_column(
        SqlEnum(Platform, name="platform", native_enum=False),
        nullable=False,
    )
    # Null only when the payload was so unreadable that no id came out of it.
    external_id: Mapped[str | None] = mapped_column(String(EXTERNAL_ID_MAX_LENGTH), nullable=True)

    # The provenance the normalised row refuses to carry.
    provider: Mapped[str] = mapped_column(String(PROVIDER_MAX_LENGTH), nullable=False)
    endpoint_key: Mapped[str] = mapped_column(String(ENDPOINT_KEY_MAX_LENGTH), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(ADAPTER_VERSION_MAX_LENGTH), nullable=False)

    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    normalization_error: Mapped[str | None] = mapped_column(
        String(NORMALIZATION_ERROR_MAX_LENGTH), nullable=True
    )
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Assigned as an object rather than an id, so the payload and the mention it was read
    # from are written in one flush and the foreign key cannot be left dangling by an
    # ordering mistake.
    mention: Mapped[Mention | None] = relationship(lazy="raise")

    def __repr__(self) -> str:
        return f"<MentionRawPayload {self.endpoint_key}:{self.external_id}>"
