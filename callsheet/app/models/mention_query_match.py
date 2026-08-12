"""Which of a title's query variants returned a given post (E03-S01).

The counterpart to deduplication. A cycle runs several overlapping queries, and a popular
post comes back on more than one of them — it must contribute *one* mention to every
chart, which is what the unique constraint on `mentions` guarantees. But collapsing those
hits to one row would also throw away the only evidence of which configured terms are
actually finding conversation, and that evidence is what alias discovery reads (E02-S04)
and what tells a studio which of its five variants is earning its cost.

So the fan-out is kept beside the mention rather than inside it: one row per
(mention, variant), never more, appended as later cycles find the same post through terms
that did not match it before. Volume reads `mentions`; attribution reads this.

A JSON list on the mention would have been fewer tables and the wrong shape — "how many
mentions did this variant find" is the question both consumers ask, and it is a GROUP BY
here versus unnesting every row's array there.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.platforms import Platform
from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin
from app.models.mention import Mention

QUERY_VARIANT_KEY_MAX_LENGTH = 320


class MatchSource(enum.StrEnum):
    """How this variant came to be credited with this post.

    The two are not interchangeable and must never be added together without saying so.
    `COLLECTION` means the variant ran as a query and the provider returned this post — it
    was paid for, and it is evidence the term finds conversation. `RETROACTIVE` means an
    alias approved after the fact (E02-S04) was checked against a post already in the
    corpus and matched it. That is worth recording, because it is what "previously
    collected posts carrying it are re-matched without paying to re-collect them" means,
    and because it tells the studio immediately how much a term they just approved is
    worth. But no query ran and nothing was spent, so counting it as a collection hit
    would credit a term with finding posts it never fetched.
    """

    COLLECTION = "collection"
    RETROACTIVE = "retroactive"


class MentionQueryMatch(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "mention_query_matches"
    __table_args__ = (
        # Two variants finding the same post is the point; the *same* variant finding it
        # on two consecutive cycles is not a second match. Polls overlap by design, so
        # without this the attribution counts would measure poll frequency.
        UniqueConstraint(
            "mention_id",
            "query_variant",
            name="uq_mention_query_match_mention_variant",
        ),
        # "Which of this title's variants are pulling their weight" — the read both
        # alias discovery and collection health run.
        Index("ix_mention_query_match_title_variant", "title_id", "query_variant"),
    )

    # Denormalised from the mention so the aggregate above is one index scan rather than
    # a join. A match cannot outlive its mention — the cascade sees to that — so the two
    # cannot drift apart.
    title_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("titles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mention_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mentions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[Platform] = mapped_column(
        SqlEnum(Platform, name="platform", native_enum=False),
        nullable=False,
    )

    # The variant's stable key ("name", "hashtag:#dcfdfs"), not the query string sent to
    # the provider. The query string carries quoting and anchor placement that may change
    # as the query builder improves; the key is what a studio's term is called, so
    # attribution survives a change in how the query is phrased.
    query_variant: Mapped[str] = mapped_column(String(QUERY_VARIANT_KEY_MAX_LENGTH), nullable=False)

    # When this variant was first *credited* with this post. Not updated on later cycles:
    # the question worth answering is when a term started working, not when it last ran.
    #
    # "Credited" rather than "returned", because a term approved from the suggestion list
    # is matched against posts already collected before it has run once (E02-S04). That
    # scan is what establishes the term matches the post, so it is what this timestamp
    # records — and it is left alone when a later real cycle upgrades `match_source`,
    # which would otherwise move a term's history forward for no reason a reader could see.
    first_matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Defaulted to COLLECTION at the database, not only in Python: every row written
    # before this column existed was a collection hit, and a backfill that had to be
    # remembered is a backfill someone eventually forgets.
    match_source: Mapped[MatchSource] = mapped_column(
        SqlEnum(MatchSource, name="mention_query_match_source", native_enum=False),
        nullable=False,
        default=MatchSource.COLLECTION,
        server_default=MatchSource.COLLECTION.name,
    )

    mention: Mapped[Mention] = relationship(lazy="raise")

    def __repr__(self) -> str:
        return f"<MentionQueryMatch {self.query_variant} -> {self.mention_id}>"
