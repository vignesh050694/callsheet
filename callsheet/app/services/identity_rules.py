"""The rules a title's identity set has to pass, in one place (E02-S01, reused by E02-S03).

Two rules live here, and they live here rather than on `TitleService` because two callers
now have to agree on them. Saving enforces them, and previewing enforces them *first* — a
preview of an identity set that cannot be saved spends a real, paid search on it and then
refuses the save for a reason the sample had already contradicted. One implementation
means the two can never drift apart.

* **The anchor rule.** A short, generic name with no person attached to it matches
  everything that shares the name — the failure the live run exposed.
* **The length bound, applied after normalisation.** NFKC expands, so the raw length a
  request carries is not the length that gets stored or queried.
"""

import structlog

from app.core.exceptions import ValidationFailedError
from app.core.identity_terms import visible_length
from app.models.title import MIN_UNANCHORED_NAME_LENGTH

_logger = structlog.get_logger(__name__)

UNANCHORED_NAME_MESSAGE = (
    "A title name shorter than {minimum} characters needs at least one cast or crew name "
    "to anchor it, otherwise collection cannot tell it apart from anything else with that name"
)
TOO_LONG_MESSAGE = (
    "{subject} is longer than {limit} characters once ligatures and compatibility "
    "characters are expanded to their standard form"
)


def ensure_fits(value: str, limit: int, subject: str) -> None:
    """Bounds a value *after* normalisation, which is the only length that matters.

    Pydantic checks `max_length` on what the client sent. Everything kept here is
    NFKC-normalised first, and NFKC **expands**: 120 copies of the ligature "ﬁ" are 120
    characters on the way in and 240 after normalisation. On the save path, without this
    the value clears validation, gets written, and then fails on the way back out — the
    read schema re-checks the same limit — which is a 500, not a 422. On Postgres the
    oversized INSERT raises `DataError`, a *sibling* of `IntegrityError` rather than a
    subclass, so the conflict handlers do not catch it either.

    The preview stores nothing, so it cannot hit that failure — but it has to refuse the
    same values, because a preview that runs happily on an identity set the save will
    reject spends a paid search to answer a question the studio is then told they may not
    ask.
    """
    if len(value) > limit:
        raise ValidationFailedError(TOO_LONG_MESSAGE.format(subject=subject, limit=limit))


def is_name_collectable(name: str, *, has_anchor_term: bool) -> bool:
    """True when this name can be queried on its own or is anchored by a person.

    Length is counted in visible characters, not code points: padding one glyph with
    combining marks or zero-width joiners must not buy a name its way past the rule.
    """
    return visible_length(name) >= MIN_UNANCHORED_NAME_LENGTH or has_anchor_term


def ensure_name_is_collectable(name: str, *, has_anchor_term: bool) -> None:
    """Raises the 422 both the setup form and the preview action answer with."""
    if is_name_collectable(name, has_anchor_term=has_anchor_term):
        return

    _logger.warning("title.identity.unanchored_name", name_length=visible_length(name))
    raise ValidationFailedError(UNANCHORED_NAME_MESSAGE.format(minimum=MIN_UNANCHORED_NAME_LENGTH))
