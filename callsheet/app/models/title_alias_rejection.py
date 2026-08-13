"""Terms a studio has looked at and said no to (E02-S04).

Suggestions are not stored. They are re-mined from the corpus on every read, because the
thing that makes one worth showing — how many posts carry it — changes with every poll,
and a stored candidate list would go stale the moment collection ran.

Decisions *are* stored, and this is half of that. Approving writes a `TitleTerm`, so the
identity set itself remembers a yes. A no has nowhere else to live: without this table the
same seven hashtags come back on every visit to the screen, and a studio who has already
ruled out `#DareDevil` is asked about it again after every poll. That is the difference
between a discovery feature and a nag.

Keyed on the folded form rather than what was typed, so a rejection survives the same
spelling drift matching already tolerates — the tag comes back from a different post with
a zero-width joiner in it and must still be recognised as the one already refused.
"""

import uuid

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.alias_candidates import AliasCandidateKind
from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin
from app.models.title import TITLE_TERM_MAX_LENGTH


class TitleAliasRejection(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "title_alias_rejections"
    __table_args__ = (
        # One row per refused term per title. Rejecting the same suggestion twice — two
        # tabs open, or a double-click — is one decision, not a conflict worth an error.
        UniqueConstraint(
            "title_id",
            "folded_value",
            name="uq_title_alias_rejection_folded",
        ),
    )

    title_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("titles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Not part of the key. A term refused as a hashtag stays refused if it later turns up
    # as a bare word: the studio's answer was about the word, not about how it was tagged.
    # It is kept so the screen can explain what was refused.
    kind: Mapped[AliasCandidateKind] = mapped_column(
        SqlEnum(AliasCandidateKind, name="alias_candidate_kind", native_enum=False),
        nullable=False,
    )
    value: Mapped[str] = mapped_column(String(TITLE_TERM_MAX_LENGTH), nullable=False)
    folded_value: Mapped[str] = mapped_column(String(TITLE_TERM_MAX_LENGTH), nullable=False)

    # Who ruled it out. An identity set is a shared object inside an organization, and
    # "why is the product not tracking #DCFDFS" is answered by a name and a date.
    rejected_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<TitleAliasRejection {self.value!r} on {self.title_id}>"
