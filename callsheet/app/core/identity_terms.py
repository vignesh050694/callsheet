"""Normalisation for title identity terms (E02-S01).

One place decides what makes two terms "the same", because dedupe on write and matching
on read have to agree. If they diverge, a set that looks clean in the UI still queries
with duplicates.

Invisible characters get explicit handling here. `str.strip()` removes spaces and control
characters but *not* the zero-width family (ZWSP, ZWNJ, ZWJ, BOM — all category Cf), so
without this a term consisting of nothing but a zero-width space reads as a real term and
can satisfy a rule that requires one. They are stripped from the edges and rejected when
they are all a term contains — but never removed from the middle, because ZWJ and ZWNJ
carry meaning inside Indic scripts and emoji sequences, which this corpus is full of.
"""

import re
import unicodedata

_WHITESPACE_RUN = re.compile(r"\s+")

# Control, format, and the separator categories — everything that occupies no visible space.
_INVISIBLE_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp", "Zs"})

# Unicode category is not a reliable proxy for "renders blank". These code points are
# classified as letters or symbols for legacy and compatibility reasons but paint nothing,
# which makes them the obvious way to fake a term that satisfies a rule requiring one.
_BLANK_RENDERING_CHARACTERS = frozenset(
    {
        "ᅟ",  # HANGUL CHOSEONG FILLER   (category Lo)
        "ᅠ",  # HANGUL JUNGSEONG FILLER  (category Lo)
        "ㅤ",  # HANGUL FILLER            (category Lo)
        "ﾠ",  # HALFWIDTH HANGUL FILLER  (category Lo)
        "⠀",  # BRAILLE PATTERN BLANK    (category So)
    }
)


def _is_invisible(character: str) -> bool:
    if character in _BLANK_RENDERING_CHARACTERS:
        return True
    return unicodedata.category(character) in _INVISIBLE_CATEGORIES


# Every mark category. A mark is not a character in its own right — it modifies the one
# before it, and with nothing before it there is nothing to modify. This is deliberately
# wider than `_COMBINING_MARK_CATEGORIES` below, which answers a different question: a
# spacing mark (`Mc`) *does* occupy width once it is attached to a letter, so it counts
# towards length, but a string containing only marks still paints no word.
_MARK_CATEGORIES = frozenset({"Mn", "Mc", "Me"})


def _renders_on_its_own(character: str) -> bool:
    """Whether this character puts something on screen without a base character to sit on.

    The question the rule actually wants to ask, asked directly rather than by listing the
    categories that fail it (E02-S06). Six earlier bypasses of the anchor rule were each a
    different Unicode neighbour — zero-width characters, Hangul fillers, the Braille blank,
    and finally variation selectors — and each fix named one more category. Variation
    selectors are `Mn`: they are real characters, they carry meaning attached to an emoji,
    and alone they render nothing at all, which is exactly the shape of every previous
    bypass.
    """
    return not _is_invisible(character) and unicodedata.category(character) not in _MARK_CATEGORIES


def has_meaningful_content(value: str) -> bool:
    """True when at least one character actually renders.

    This is the emptiness test for terms — `not value` is not enough, because a string of
    zero-width characters is truthy and looks empty to everyone reading the screen, and a
    string of combining marks is truthy and paints, at most, a dotted placeholder circle.

    One predicate, three callers: title names, identity terms, and campaign milestone
    names. That is the argument for fixing this rather than each caller — a term made of a
    variation selector satisfied the anchor rule *and* painted an unlabelled marker on the
    campaign timeline, which are two bugs from one wrong answer.
    """
    return any(_renders_on_its_own(character) for character in value)


# Non-spacing (Mn) and enclosing (Me) marks paint on top of the character before them and
# add no width. Spacing marks (Mc) are deliberately NOT here: the vowel signs of Devanagari,
# Telugu, Tamil and their neighbours are Mc, and they occupy their own rendered width — they
# are part of the word, not decoration on it. Excluding them made ordinary regional titles
# like "राधे" and "మజిలీ" count as two or three characters and demand a spurious anchor term.
_COMBINING_MARK_CATEGORIES = frozenset({"Mn", "Me"})


def visible_length(value: str) -> int:
    """How many characters this actually paints, near enough for a length rule.

    `len()` counts code points, which is the wrong unit for a rule about how short and
    generic a name looks: three combining accents on one letter are four code points and
    one glyph, and an emoji joined by ZWJ is one glyph and five. Counting only base
    characters — skipping combining marks and anything invisible — undercounts a few
    scripts rather than overcounting, so the rule errs towards demanding an anchor. For a
    product measured on entity-match precision, that is the safe direction to be wrong in.
    """
    return sum(
        1
        for character in value
        if not _is_invisible(character)
        and unicodedata.category(character) not in _COMBINING_MARK_CATEGORIES
    )


def _strip_invisible_edges(value: str) -> str:
    start = 0
    end = len(value)
    while start < end and _is_invisible(value[start]):
        start += 1
    while end > start and _is_invisible(value[end - 1]):
        end -= 1
    return value[start:end]


def normalize_term(raw_value: str) -> str:
    """Casefold, strip leading hashes, and collapse whitespace.

    NFKC first, so a term pasted from a post with composed characters compares equal to
    the same term typed by hand — this corpus is multilingual and that difference is
    invisible on screen. Every leading `#` is removed, not just one, so `##DC` and `#DC`
    and `DC` all land on the same value.
    """
    normalized = unicodedata.normalize("NFKC", raw_value)
    normalized = _strip_invisible_edges(normalized)
    normalized = normalized.lstrip("#")
    normalized = _strip_invisible_edges(normalized)
    normalized = _WHITESPACE_RUN.sub(" ", normalized).strip()
    return normalized.casefold()


# ZWJ and ZWNJ control whether adjacent consonants form a conjunct. They are kept in the
# stored forms — removing them would fragment words — but two renderings of the *same*
# word that differ only by one are the same word, and a hashtag copied between apps
# routinely picks one up or loses one.
_ZERO_WIDTH_JOINERS = ("‌", "‍")


def joiner_folded(value: str) -> str:
    """A comparison-only view of a term, with the zero-width joiners dropped.

    Never store or display this. `normalize_term` keeps joiners because they carry
    meaning inside a word; this answers the narrower question of whether two terms *are*
    the same word, which is what matching, deduping, and the exclusion guard all ask.

    Without it those three disagree with each other in a way nobody can see on screen:
    `#தமிழ்சினிமா` typed by the studio and `#தமிழ்<ZWNJ>சினிமா` in a post render alike,
    so the preview would report the studio's own hashtag as contamination and then let
    them exclude it.
    """
    for joiner in _ZERO_WIDTH_JOINERS:
        value = value.replace(joiner, "")
    return value


def clean_display_value(raw_value: str) -> str:
    """What the studio typed, tidied but not transformed — this is shown back to them.

    Keeps the leading `#` and the original case; strips only what should never have been
    carried in, so a pasted term does not smuggle an invisible character into the UI.
    """
    cleaned = unicodedata.normalize("NFKC", raw_value)
    cleaned = _strip_invisible_edges(cleaned)
    return _WHITESPACE_RUN.sub(" ", cleaned).strip()
