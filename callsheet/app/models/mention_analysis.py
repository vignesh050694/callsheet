"""Derived fields, versioned by the pipeline that produced them (E03-S04).

A separate table from `mentions` for one reason: what the platform said and what a model
concluded have different lifetimes. The platform's words are a fact recorded once. A
model's judgement is provisional, gets better, and must be replaceable without touching
the record of what was actually collected.

The key is `(mention_id, pipeline_version)`, so runs are additive rather than destructive.
Reprocessing under a new version writes new rows beside the old ones, which means the
dashboard keeps working throughout a long re-run, a regression can be diffed against the
version it replaced, and rolling back is a change of which version is read rather than
another pass over the corpus.

Every judgement column is nullable, and null means "this version did not judge that". The
pipeline is assembled from steps that ship separately (E04-S01 language, S02 sentiment,
S03 account type, S04 themes), so a version that only detects language is normal and must
not be forced to invent a sentiment.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin
from app.models.mention import Mention

PIPELINE_VERSION_MAX_LENGTH = 60
DETECTED_LANGUAGE_MAX_LENGTH = 60
ACCOUNT_TYPE_MAX_LENGTH = 40
SENTIMENT_LABEL_MAX_LENGTH = 30


class MentionAnalysis(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "mention_analyses"
    __table_args__ = (
        # One verdict per mention per pipeline version. A reprocess that runs twice under
        # the same version is a repeat, not a second opinion.
        UniqueConstraint(
            "mention_id",
            "pipeline_version",
            name="uq_mention_analysis_mention_pipeline_version",
        ),
        # Every read is "this title's mentions under the version we currently trust".
        Index("ix_mention_analysis_title_pipeline", "title_id", "pipeline_version"),
    )

    mention_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mentions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalised from the mention so a title's analyses can be counted, replaced, or
    # scoped to a version without joining the corpus table. A reprocess targets a title,
    # and this is what makes that a single indexed read.
    title_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("titles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pipeline_version: Mapped[str] = mapped_column(
        String(PIPELINE_VERSION_MAX_LENGTH), nullable=False
    )

    # E04-S01. Distinct from `Mention.platform_reported_language`, which stays as the
    # diagnostic it always was — keeping both is what lets the disagreement rate be
    # measured instead of assumed.
    detected_language: Mapped[str | None] = mapped_column(
        String(DETECTED_LANGUAGE_MAX_LENGTH), nullable=True
    )
    language_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_code_mixed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # E04-S03. The field account-type segmentation reads, so an aggregate can say which
    # segment it describes rather than silently mixing trade and organic accounts.
    account_type: Mapped[str | None] = mapped_column(
        String(ACCOUNT_TYPE_MAX_LENGTH), nullable=True
    )
    account_type_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # E04-S02.
    sentiment_label: Mapped[str | None] = mapped_column(
        String(SENTIMENT_LABEL_MAX_LENGTH), nullable=True
    )
    sentiment_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # E04-S04.
    themes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    mention: Mapped[Mention] = relationship(lazy="raise")

    def __repr__(self) -> str:
        return f"<MentionAnalysis {self.mention_id} v{self.pipeline_version}>"
