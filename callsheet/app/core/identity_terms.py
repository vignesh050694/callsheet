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

# The joiner that *fuses* — it makes what follows part of the cluster before it, which is
# how an emoji family is one glyph and how two Indic consonants form one conjunct. Its
# sibling ZWNJ (U+200C) is deliberately not here: it does the opposite, keeping the two
# sides apart, so it should leave them counted as two.
_ZERO_WIDTH_JOINER = "\u200d"

# A joiner only fuses after one of these, and one sitting between two ordinary letters
# fuses nothing \u2014 which is exactly what a stray joiner copied in from another app is.
# Getting this wrong in the permissive direction is not harmless: two stray joiners took a
# real Tamil title from five clusters to three and would have demanded an anchor term for a
# name a reader would call long enough.
#
# The viramas of the scripts this corpus is actually written in, listed rather than derived
# from the Unicode combining class. The client mirror cannot ask for a combining class at
# all, and a rule the two sides implement differently is worse than one that names its own
# limits \u2014 a divergence here is the form's submit button disagreeing with the server.
#
# Every code point with combining class 9 in these scripts, not one per script: Malayalam
# has three (the plain virama plus the vertical-bar and circular forms) and listing only
# the obvious one made two real Malayalam conjuncts count as two clusters instead of one.
# Written as escapes rather than as the characters themselves. These are invisible or
# near-invisible in every editor and diff, and pasting them by hand is how a *letter*
# (U+0D3A MALAYALAM LETTER TTTA) got into this set on the first attempt at it \u2014 where it
# would have fused two ordinary letters into one cluster. An escape can be checked against
# the Unicode charts by reading it; a pasted glyph cannot.
_VIRAMAS = frozenset(
    {
        "\u094d",  # Devanagari
        "\u09cd",  # Bengali
        "\u0a4d",  # Gurmukhi
        "\u0acd",  # Gujarati
        "\u0b4d",  # Odia
        "\u0bcd",  # Tamil
        "\u0c4d",  # Telugu
        "\u0ccd",  # Kannada
        "\u0d3b",  # Malayalam, vertical bar
        "\u0d3c",  # Malayalam, circular
        "\u0d4d",  # Malayalam
        "\u0dca",  # Sinhala al-lakuna
    }
)

# The skin-tone modifiers. They are category `Sk`, so nothing else here treats them as
# part of the character before them \u2014 but they are, and a title made of one emoji whose
# base carries a skin tone was measured as two things a reader sees rather than one.
# Listed as a range because Python has no `Emoji_Modifier` property; the client mirror
# asks for that property by name, and it is these same five code points.
_EMOJI_MODIFIERS = frozenset(chr(code_point) for code_point in range(0x1F3FB, 0x1F400))

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
# before it, and with nothing before it there is nothing to modify.
#
# All three, including the spacing marks (`Mc`) that do occupy their own width. An earlier
# version of the length rule kept `Mc` separate on the grounds that a Devanagari vowel sign
# is visible, which is true and was the wrong conclusion: it is visible *as part of the
# syllable it attaches to*, not as a thing of its own, and counting it separately is what
# made `सीता` two characters longer than `राधे` to this code and identical to a reader
# (E02-S07). One list, one meaning: a mark never stands alone and never counts alone.
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


def visible_length(value: str) -> int:
    """How many things a reader sees here — grapheme clusters, not code points (E02-S07).

    The rule this feeds asks "is this name short and generic enough to be uncollectable on
    its own", which is a question about what a person looking at the name perceives. Every
    other unit gets that wrong on this corpus:

    * `len()` counts code points, so three combining accents on one letter are four.
    * Counting base characters plus *spacing* marks — what this did before — splits an
      akshara in two. In Devanagari and its neighbours the common syllable is a consonant
      plus a spacing vowel sign, `Lo`+`Mc`, so `सीता` counted 4 and sailed through the rule
      while `राधे` counted 3 and was refused. Two names of the same perceived length, two
      different answers, and no reader could tell why.

    So: one count per character that renders on its own, with its marks folded into it.
    `राधे` and `सीता` are both 2, `మజిలీ` is 3. A zero-width joiner binds what follows into
    the cluster before it, which is what makes a joined emoji one glyph rather than three,
    and what makes an Indic conjunct one syllable rather than two.

    **This is a behaviour change, and it is the point of the story rather than a side
    effect.** Names like `सीता` that were accepted with no cast or crew term now require
    one. That is the intended reading of the anchor rule — it always meant "short names are
    not collectable alone" — and the previous behaviour was letting some short names past
    on an accident of which script they were written in.
    """
    count = 0
    # The two things a joiner needs to know about what came before it, which are not the
    # same character. A virama sits immediately before the joiner; the symbol an emoji
    # sequence is being built from is the *base* of the cluster, which a skin-tone
    # modifier or a variation selector can be sitting between.
    previous: str | None = None
    cluster_base: str | None = None
    joiner_follows: str | None = None
    joiner_follows_base: str | None = None

    for character in value:
        if character == _ZERO_WIDTH_JOINER:
            # Nothing counted yet means there is nothing to fuse onto.
            joiner_follows = previous if count else None
            joiner_follows_base = cluster_base if count else None
            previous = character
            continue

        if character in _EMOJI_MODIFIERS or not _renders_on_its_own(character):
            # Marks, invisibles and skin tones belong to the cluster already counted, and
            # a mark with no base before it renders nothing at all.
            previous = character
            continue

        if joiner_follows is not None and _joiner_fuses(
            joiner_follows, joiner_follows_base, character
        ):
            # Fused into the cluster before it, but it becomes that cluster's base — an
            # emoji family chains joiner after joiner and each one fuses onto the last.
            joiner_follows = joiner_follows_base = None
            previous = cluster_base = character
            continue

        joiner_follows = joiner_follows_base = None
        previous = cluster_base = character
        count += 1

    return count


def _shares_script_block(left: str, right: str) -> bool:
    """Whether two characters come from the same Indic script block.

    Every one of these scripts occupies its own aligned 128-code-point block — Devanagari
    at U+0900, Bengali at U+0980, and so on down to Sinhala at U+0D80 — so shifting away
    the low seven bits names the block. That is the whole test, and it is deliberately
    arithmetic rather than a Unicode script lookup: the client mirror has no way to ask for
    a character's script, and a rule the two sides compute differently is worse than one
    that says out loud what it approximates.

    It exists because "is the next character a letter" is not enough. A Devanagari virama
    followed by a joiner and the Latin letter `A` fused into one cluster, since `A` is
    unquestionably a letter — but no font stacks a Devanagari consonant onto it, and the
    name it shortened was measured one character shorter than a reader sees.
    """
    return ord(left) >> 7 == ord(right) >> 7


def _joiner_fuses(before: str, before_base: str | None, after: str) -> bool:
    """Whether a joiner between these actually makes one glyph of them.

    The two cases where a joiner does real work, and no others:

    * **After a virama, in front of a letter.** In Indic scripts the virama plus a joiner
      is the request for a conjunct — two consonants drawn as one stacked form. `after`
      has to be a letter, or the joiner is being asked to stack a consonant onto a digit.
    * **Between two symbols.** This is how an emoji family is assembled: 👨 ZWJ 👩 ZWJ 👧
      renders as one glyph, and counting it as three would let a one-glyph name skip the
      anchor rule. The test is against the *cluster's base* rather than the character
      literally before the joiner, because a skin tone or a variation selector routinely
      sits in between — and reading the literal character there is how a two-person emoji
      with skin tones measured four.

    Anywhere else a joiner is inert, and treating it as fusing would let a stray one —
    copied in from another app, invisible on screen — silently shorten a name past the
    threshold and demand an anchor term for a title that never needed one.
    """
    if before in _VIRAMAS:
        return unicodedata.category(after).startswith("L") and _shares_script_block(before, after)
    base = before_base if before_base is not None else before
    return unicodedata.category(base) == "So" and unicodedata.category(after) == "So"


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
