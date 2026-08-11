"""Explaining why a post matched, and what in it looks like contamination (E02-S03).

A preview is only worth running if the studio can tell *why* each post is in the sample.
"Author, text, and why it matched" is the difference between a list they have to take on
faith and one they can audit — and auditing it is the entire feature.

The same pass produces the other half: the terms in a post that are *not* in the identity
set. When the studio marks a post "not my title", those are the candidates for an
exclusion rule, because one of them is what dragged the post in. The live corpus made
this concrete — a post carrying `#DC #DareDevil` matched on `#DC` and was contaminated by
`#DareDevil`, and only the second one is worth excluding.

Word boundaries are decided in Python rather than by a regex, because `\\w` is the wrong
alphabet for this corpus. It excludes categories Mn and Mc, which is where the dependent
vowel signs and the virama of every Indic script live: `\\w+` reads `#தமிழ்சினிமா` as
`#தம`, stopping at the first vowel sign. A truncated tag is not a word in any language,
and offering one back as a rule to exclude is worse than offering nothing.
"""

import re
import unicodedata
from collections.abc import Iterable, Iterator, Sequence

from app.core.identity_terms import joiner_folded

_WHITESPACE_RUN = re.compile(r"\s+")

# Marks attach to the character before them and are part of the word they sit in.
_MARK_CATEGORIES = frozenset({"Mn", "Mc", "Me"})

# ZWJ and ZWNJ sit *inside* words in Indic scripts, controlling whether adjacent
# consonants form a conjunct — `normalize_term` keeps them mid-string for exactly this
# reason. They have to count as word characters here or the same word breaks two ways:
# `#தமிழ்<ZWNJ>சினிமா` would be extracted as the truncated `#தமிழ்`, and the short term
# `தமிழ்` would falsely match inside the compound it was joined into. Only these two —
# the rest of category Cf (zero-width space, BOM, bidi controls) genuinely separates
# words, and treating those as word characters would let an invisible character glue two
# unrelated terms together.
_JOINING_CHARACTERS = frozenset({"‌", "‍"})

_HASH = "#"
_UNDERSCORE = "_"


def _is_word_character(character: str) -> bool:
    """Whether this character continues a word — the alphabet this corpus is written in."""
    if character.isalnum() or character == _UNDERSCORE:
        return True
    if character in _JOINING_CHARACTERS:
        return True
    return unicodedata.category(character) in _MARK_CATEGORIES


def _comparable(value: str) -> str:
    """The form matching happens in: composed, casefolded, single-spaced, joiners dropped.

    Mirrors `normalize_term` minus the hash-stripping, which would be wrong here — the
    hashes in a post's text are part of the haystack, and stripping the leading one from
    a whole post would only ever mangle the first word.

    Joiners come out on both sides of every comparison (see `joiner_folded`), so a term
    and a post that render the same word differently still compare equal. Dropping them
    does not weaken the word boundaries: `தமிழ்` still fails to match inside
    `தமிழ்<ZWJ>சினிமா`, because once the joiner is gone the next character is a letter,
    which is what the boundary check reads.
    """
    folded = unicodedata.normalize("NFKC", value).casefold()
    return joiner_folded(_WHITESPACE_RUN.sub(" ", folded).strip())


def _occurs_in(haystack: str, normalized_term: str) -> bool:
    """Whole-word containment, so `DC` does not match inside `abcdcx`.

    Both edges are checked against `_is_word_character`, which is what makes this correct
    in both directions for marked scripts: `தமிழ` must not match inside `தமிழா`, where
    the extra character is a spacing vowel sign rather than a letter.

    A bare term still matches its hashtag form — `#` is not a word character, so `96movie`
    is found inside `#96movie`, which is exactly how studios type these two ways round.
    """
    if not normalized_term:
        return False

    start = haystack.find(normalized_term)
    while start != -1:
        end = start + len(normalized_term)
        starts_cleanly = start == 0 or not _is_word_character(haystack[start - 1])
        ends_cleanly = end == len(haystack) or not _is_word_character(haystack[end])
        if starts_cleanly and ends_cleanly:
            return True
        start = haystack.find(normalized_term, start + 1)
    return False


def _iter_hashtags(text: str) -> Iterator[str]:
    """Yields each hashtag's body, in the order it appears, hash excluded.

    `##DC` yields `DC` once: the first hash is followed by another hash rather than a word
    character, so it opens nothing and the scan resumes at the second.
    """
    index = 0
    while index < len(text):
        if text[index] != _HASH:
            index += 1
            continue
        end = index + 1
        while end < len(text) and _is_word_character(text[end]):
            end += 1
        if end > index + 1:
            yield text[index + 1 : end]
            index = end
        else:
            index += 1


def find_matching_terms(
    haystacks: Sequence[str],
    terms: Sequence[tuple[str, str]],
) -> list[str]:
    """Which identity terms appear anywhere in this post, in the order they were given.

    `terms` are `(display value, normalised value)` pairs: matching happens on the
    normalised form, and the display form is what gets shown back, because the studio
    should see the term the way they typed it.
    """
    combined = _comparable(" \n".join(haystacks))
    matched: list[str] = []
    seen: set[str] = set()
    for display_value, normalized_value in terms:
        # The needle is folded to match the haystack. `normalize_term` keeps joiners, so
        # without this a term typed without one would miss the same word carrying one.
        comparable_term = joiner_folded(normalized_value)
        if not comparable_term or comparable_term in seen:
            continue
        if _occurs_in(combined, comparable_term):
            seen.add(comparable_term)
            matched.append(display_value)
    return matched


def suggest_exclusion_terms(text: str, known_terms: Iterable[str], limit: int) -> list[str]:
    """Hashtags in the post that the identity set does not already claim.

    Only hashtags, deliberately. Every other word in a post is a candidate for excluding
    in the sense that it appears there, and offering the studio a wall of ordinary words
    invites a rule broad enough to delete their own corpus. A hashtag is a claim about
    what the post is about, which is what an exclusion is too.
    """
    # Folded on both sides, so a hashtag the studio declared is never offered back to them
    # as contamination just because the post spells it with a joiner.
    known = {joiner_folded(term) for term in known_terms if term}
    suggestions: list[str] = []
    seen: set[str] = set()
    for tag in _iter_hashtags(text):
        comparable = _comparable(tag)
        if not comparable or comparable in known or comparable in seen:
            continue
        seen.add(comparable)
        suggestions.append(f"{_HASH}{tag}")
        if len(suggestions) == limit:
            break
    return suggestions
