"""Reading values out of a vendor payload without trusting it (E03-S07).

Every helper here exists because a real captured response broke the obvious version of it.
The two X providers were captured minutes apart, against the same query, and still
disagreed about types, field names, and which field holds the whole post — so an adapter
that reads `payload["views"] + 1` or `datetime.fromisoformat(...)` is one provider change
away from a 500 in the middle of a poll.
"""

import html
import unicodedata
from collections.abc import Mapping
from datetime import datetime
from typing import Any

# "Tue Aug 11 17:41:52 +0000 2026" — X's legacy timestamp, still what both providers emit.
_X_TIMESTAMP_FORMAT = "%a %b %d %H:%M:%S %z %Y"


class PayloadShapeError(ValueError):
    """A payload item could not be read as a mention.

    Raised rather than returned so an adapter cannot half-build a mention. The collector
    catches it per item: one unreadable post must not discard the page around it, and the
    raw payload is stored either way so the item can be re-read once the adapter is fixed.
    """


def require_string(item: Mapping[str, Any], *keys: str) -> str:
    """The first key present with a non-empty string value, or a shape error naming them all."""
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    raise PayloadShapeError(f"none of {keys} held a usable string")


def optional_string(item: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def optional_int(value: Any) -> int | None:
    """Counts arrive as ints from one provider and strings from another.

    tikhub returns `favorites: 0` but `views: "87"` in the same object; apify returns
    `viewCount: 93`. Neither is wrong, and both have to end up as one integer column.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip().replace(",", "")
        if stripped.isdigit():
            return int(stripped)
    return None


def parse_x_timestamp(raw_value: Any) -> datetime:
    """X's legacy format, which both providers emit unchanged.

    Not ISO 8601, so `fromisoformat` fails on it. Always carries an offset, so the result
    is timezone-aware and safe to compare against a release date.
    """
    if not isinstance(raw_value, str):
        raise PayloadShapeError(f"timestamp was {type(raw_value).__name__}, not a string")
    try:
        return datetime.strptime(raw_value, _X_TIMESTAMP_FORMAT)
    except ValueError as error:
        raise PayloadShapeError(f"unreadable timestamp {raw_value!r}") from error


def clean_post_text(raw_value: str) -> str:
    """Undo the vendor's transport encoding, and nothing else.

    Both providers return `&amp;` where the post said `&`. Left alone it reaches the
    studio's screen as-is and, worse, breaks term matching on any title with an ampersand
    in it. NFKC follows, so text pasted from a post compares equal to the same term typed
    into setup — the same normalisation the identity set already uses.

    The post's own words are otherwise untouched: no case folding, no emoji stripping, no
    link removal. This corpus is code-mixed and emoji-dense, and every one of those is
    signal for the analysis pipeline.
    """
    return unicodedata.normalize("NFKC", html.unescape(raw_value)).strip()


def longest_text(*candidates: str | None) -> str:
    """The fullest version of the post among the fields a provider offers.

    Not a preference for one field name. The apify capture returned an item whose `text`
    held the entire 3,900-character review while its `fullText` was truncated to 272
    characters plus a t.co link — the opposite of what the names imply. Taking whichever
    is longer is the only rule that survives both providers.
    """
    usable = [candidate for candidate in candidates if isinstance(candidate, str) and candidate]
    if not usable:
        raise PayloadShapeError("no post text in any known field")
    return max(usable, key=len)


def read_hashtag_texts(entities: Any) -> list[str]:
    """Hashtag bodies as the platform tagged them, order preserved, hash excluded.

    Taken from the provider's own entity list rather than re-scanned out of the text: the
    platform already knows where its tags are, and it is right about tags this product's
    own scanner would have to guess at. Case is left alone — `#DCMovie` and `#dcmovie`
    both appeared in the capture, and folding them here would destroy the evidence
    alias discovery (E02-S04) needs to rank them.
    """
    if not isinstance(entities, Mapping):
        return []
    raw_hashtags = entities.get("hashtags")
    if not isinstance(raw_hashtags, list):
        return []

    texts: list[str] = []
    for hashtag in raw_hashtags:
        if not isinstance(hashtag, Mapping):
            continue
        text = hashtag.get("text")
        if isinstance(text, str) and text.strip():
            texts.append(text.strip())
    return texts
