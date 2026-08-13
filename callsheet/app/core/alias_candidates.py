"""Mining a title's own corpus for identity terms nobody declared (E02-S04).

The live run made the case: twenty posts produced seven organic hashtags — `#DCthemovie`,
`#DCFDFS`, `#DCPublicReview` — and a misspelt director ("Kankaraj"). None of those could
have been typed at setup, because they did not exist yet. An identity set that is only
declared goes stale the moment the audience invents a tag, and the conversation carries on
under a name the product is not listening for.

Two kinds of candidate, and they are found in different ways because they *are* different
claims:

* **A hashtag** is the audience naming the thing. It is taken at face value — any tag in
  the corpus that the identity set does not already claim is a candidate.
* **A name variant** is the audience getting a declared name slightly wrong. It is only a
  candidate if it nearly matches something the studio already declared, because the
  alternative — offering every unfamiliar word in the corpus — is a list nobody can read
  and a route to approving a term that collects the wrong film.

Nothing here touches the database or the network. It is given posts and returns ranked
candidates, which is what makes the ranking testable against a fixed corpus.
"""

import enum
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.core.identity_terms import has_meaningful_content, joiner_folded, normalize_term
from app.core.post_matching import iter_hashtags, iter_words

# Below this, edit distance stops meaning anything: "DC" is one edit from "DE", "AC" and
# "DB", none of which is a misspelling of it. Short declared terms are matched exactly or
# not at all.
MIN_VARIANT_LENGTH = 4

# A declared term of more words than this is not compared for variants. Film identity
# terms are names — "Lokesh Kanagaraj", "Drug Cartel" — and sliding a six-word window over
# every post to find a near-match of a six-word term costs more than it finds.
MAX_VARIANT_WORDS = 4

# One word of a multi-word name is only compared on its own if it is at least this long.
# See `_variant_targets` — six is where a near-match stops being a coincidence.
MIN_SUBWORD_VARIANT_LENGTH = 6

_HASH = "#"


class AliasCandidateKind(enum.StrEnum):
    """What kind of claim this candidate is, which decides how it is offered back.

    Kept apart because approving them means two different things: a hashtag joins the set
    as a hashtag and is queried bare, while a name variant is an alias and is queried
    anchored to a person. Collapsing them would silently change which query a studio
    thinks they approved.
    """

    HASHTAG = "hashtag"
    NAME_VARIANT = "name_variant"


@dataclass(frozen=True, slots=True)
class MinedPost:
    """One post as the miner needs it — deliberately not an ORM row.

    `hashtags` is what the platform tagged, which is not always what the text contains:
    some providers return tags the post carries in an attachment, and some strip them from
    the text entirely. Both sources are read.
    """

    id: uuid.UUID
    text: str
    hashtags: Sequence[str] = ()


@dataclass(frozen=True, slots=True)
class AliasCandidate:
    """One term the corpus is using that the identity set does not claim."""

    kind: AliasCandidateKind
    value: str
    normalized_value: str
    folded_value: str
    mention_count: int
    sample_mention_id: uuid.UUID
    # Which declared term this is a near-miss of. Null for hashtags, which resemble
    # nothing — they are offered on their own volume.
    resembles: str | None = None


def folded_key(raw_value: str) -> str:
    """The one form two spellings of a term are compared on.

    `normalize_term` for the storage form, then the joiner fold on top, because that is
    the equivalence the identity set already dedupes and matches on (E02-S03 round 2). A
    candidate mined out of a post carries that post's zero-width joiners; the declared
    term carries the studio's. Comparing the stored forms would offer a studio their own
    hashtag back as a discovery.
    """
    return joiner_folded(normalize_term(raw_value))


@dataclass
class _Accumulator:
    """One candidate as it is being counted across the corpus."""

    kind: AliasCandidateKind
    normalized_value: str
    sample_mention_id: uuid.UUID
    resembles: str | None
    mention_count: int = 0
    # Every spelling seen, and how often. The audience types `#DCFDFS` and `#dcfdfs`; the
    # studio should be offered the one they actually use.
    spellings: dict[str, int] = field(default_factory=dict)

    def observe(self, display_value: str) -> None:
        self.mention_count += 1
        self.spellings[display_value] = self.spellings.get(display_value, 0) + 1

    def promote_to_hashtag(self, normalized_value: str) -> None:
        """A term first seen as a bare word is a hashtag if it is ever tagged as one.

        Order-independent on purpose: whichever post the tag turns up in, the candidate
        ends up the same kind, so the list does not depend on the order the corpus is
        walked in.
        """
        self.kind = AliasCandidateKind.HASHTAG
        self.normalized_value = normalized_value
        self.resembles = None

    def best_spelling(self) -> str:
        """The commonest spelling, ties broken lexicographically so it never wobbles."""
        return min(self.spellings.items(), key=lambda entry: (-entry[1], entry[0]))[0]


def mine_alias_candidates(
    posts: Iterable[MinedPost],
    *,
    declared_terms: Sequence[str],
    rejected: Iterable[str],
    limit: int,
) -> list[AliasCandidate]:
    """Ranked candidates from this corpus, commonest first.

    `declared_terms` is the whole identity set *including exclusions and the title name*:
    a term the studio has already ruled out must not come back as a discovery, and neither
    must the film's own name. `rejected` is the folded form of everything they have
    already said no to.

    Ranked by how many posts carry the term, not by recency — the story's requirement, and
    the reason a suggestion list stays readable during a review wave. Ties break on the
    folded value, so the list is a total order and cannot reshuffle between two reads of an
    unchanged corpus.
    """
    if limit <= 0:
        return []

    claimed = {folded for folded in (folded_key(term) for term in declared_terms) if folded}
    off_limits = claimed | {folded for folded in (folded_key(term) for term in rejected) if folded}
    variant_targets = _variant_targets(declared_terms)

    accumulators: dict[str, _Accumulator] = {}
    for post in posts:
        _mine_post(post, off_limits, variant_targets, accumulators)

    ranked = sorted(
        accumulators.items(),
        key=lambda entry: (-entry[1].mention_count, entry[0]),
    )
    return [
        AliasCandidate(
            kind=accumulator.kind,
            value=accumulator.best_spelling(),
            normalized_value=accumulator.normalized_value,
            folded_value=folded,
            mention_count=accumulator.mention_count,
            sample_mention_id=accumulator.sample_mention_id,
            resembles=accumulator.resembles,
        )
        for folded, accumulator in ranked[:limit]
    ]


def _mine_post(
    post: MinedPost,
    off_limits: set[str],
    variant_targets: dict[int, list[tuple[str, str]]],
    accumulators: dict[str, _Accumulator],
) -> None:
    """Counts one post's candidates, each at most once however often it repeats in it.

    A post that spams `#DCFDFS` eleven times is one post talking about the film, not
    eleven. Counting occurrences rather than posts is how a single account's thread
    becomes the top suggestion.
    """
    counted: set[str] = set()

    for raw_tag in _iter_post_hashtags(post):
        folded = folded_key(raw_tag)
        if not _is_offerable(folded, off_limits):
            continue
        display_value = f"{_HASH}{raw_tag.lstrip(_HASH)}"
        existing = accumulators.get(folded)
        if existing is None:
            accumulators[folded] = _Accumulator(
                kind=AliasCandidateKind.HASHTAG,
                normalized_value=normalize_term(raw_tag),
                sample_mention_id=post.id,
                resembles=None,
            )
        elif existing.kind is not AliasCandidateKind.HASHTAG:
            existing.promote_to_hashtag(normalize_term(raw_tag))
        if folded in counted:
            continue
        counted.add(folded)
        accumulators[folded].observe(display_value)

    for display_value, folded, resembles in _iter_name_variants(post.text, variant_targets):
        if folded in counted or not _is_offerable(folded, off_limits):
            continue
        counted.add(folded)
        accumulator = accumulators.get(folded)
        if accumulator is None:
            accumulator = _Accumulator(
                kind=AliasCandidateKind.NAME_VARIANT,
                normalized_value=normalize_term(display_value),
                sample_mention_id=post.id,
                resembles=resembles,
            )
            accumulators[folded] = accumulator
        accumulator.observe(display_value)


def _is_offerable(folded: str, off_limits: set[str]) -> bool:
    """A candidate has to render something and must not already be settled."""
    return bool(folded) and has_meaningful_content(folded) and folded not in off_limits


def _iter_post_hashtags(post: MinedPost) -> Iterable[str]:
    """Tags from the text and from the platform's own list, text first."""
    yield from iter_hashtags(post.text)
    yield from (tag for tag in post.hashtags if tag)


def _variant_targets(declared_terms: Sequence[str]) -> dict[int, list[tuple[str, str]]]:
    """Declared terms worth looking for misspellings of, bucketed by word count.

    Bucketed because a variant of a two-word name is a two-word phrase: comparing
    "Lokesh Kanagaraj" against single words would find nothing, and comparing it against
    every window length would find nonsense.

    **Each long word of a multi-word name is also a target on its own**, reporting the
    whole name as what it resembles. This is the case the story names: people misspell the
    surname, not the full name — the live corpus carried "Kankaraj", never
    "Lokesh Kankaraj". Bucketing only by the full phrase would find the variant that
    happens to be written out in full and miss the commonest form of the mistake entirely.

    Only words of `MIN_SUBWORD_VARIANT_LENGTH` or more, because that is where the noise
    is: a four-letter word of a title is one edit from a dozen ordinary English words, and
    a suggestion list full of those is one nobody reads to the end of.
    """
    targets: dict[int, list[tuple[str, str]]] = {}
    seen: set[tuple[int, str]] = set()

    def register(display_term: str, folded_term: str) -> None:
        width = len(folded_term.split(" "))
        if (width, folded_term) in seen:
            return
        seen.add((width, folded_term))
        targets.setdefault(width, []).append((display_term, folded_term))

    for term in declared_terms:
        folded = folded_key(term)
        if len(folded) < MIN_VARIANT_LENGTH:
            continue
        words = folded.split(" ")
        if not (1 <= len(words) <= MAX_VARIANT_WORDS):
            continue
        register(term, folded)
        if len(words) == 1:
            continue
        for word in words:
            if len(word) >= MIN_SUBWORD_VARIANT_LENGTH:
                register(term, word)
    return targets


def _iter_name_variants(
    text: str, variant_targets: dict[int, list[tuple[str, str]]]
) -> Iterable[tuple[str, str, str]]:
    """Windows of this post's words that are near-misses of a declared term.

    Yields `(display value, folded value, the term it resembles)`. The display value is
    rebuilt from the words as they were written, so the studio is shown the misspelling
    rather than a normalised version of it — the misspelling is the whole point.
    """
    if not variant_targets:
        return

    words = list(iter_words(text))
    if not words:
        return
    folded_words = [folded_key(word) for word in words]

    for width, targets in variant_targets.items():
        for start in range(0, len(words) - width + 1):
            window = folded_words[start : start + width]
            if any(not part for part in window):
                continue
            candidate = " ".join(window)
            if len(candidate) < MIN_VARIANT_LENGTH:
                continue
            resembles = _nearest_target(candidate, targets)
            if resembles is None:
                continue
            yield " ".join(words[start : start + width]), candidate, resembles


def _nearest_target(candidate: str, targets: Sequence[tuple[str, str]]) -> str | None:
    """The declared term this window is a misspelling of, or nothing.

    Ties are broken by the declared term's folded form so the answer is stable — two
    declared spellings of one person are both "the term this resembles" and only one can
    be reported.
    """
    best: tuple[int, str, str] | None = None
    for display_term, folded_term in targets:
        allowance = _edit_allowance(len(folded_term))
        distance = _bounded_edit_distance(candidate, folded_term, allowance)
        # Zero means the window *is* the declared term. Not a variant, and letting it
        # through would offer the studio their own term back with a different spelling.
        if distance is None or distance == 0:
            continue
        if best is None or (distance, folded_term) < (best[0], best[1]):
            best = (distance, folded_term, display_term)
    return None if best is None else best[2]


def _edit_allowance(length: int) -> int:
    """How wrong a word may be and still be the same name.

    One edit for a short name, two for a long one. Fixed rather than proportional: a
    proportional allowance on a fifteen-character name admits three edits, which is enough
    to reach a different person's name entirely.
    """
    return 1 if length <= 8 else 2


def _bounded_edit_distance(left: str, right: str, allowance: int) -> int | None:
    """Levenshtein distance, or `None` once it is certainly over the allowance.

    Bounded rather than full, because this runs per window per declared term over a whole
    corpus. The length check alone discards most pairs before any matrix is built.
    """
    if abs(len(left) - len(right)) > allowance:
        return None

    previous = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_character in enumerate(right, start=1):
            current.append(
                min(
                    previous[right_index] + 1,
                    current[right_index - 1] + 1,
                    previous[right_index - 1] + (left_character != right_character),
                )
            )
        # Every remaining row can only add to the best value on this one, so a row whose
        # cheapest cell already exceeds the allowance settles it.
        if min(current) > allowance:
            return None
        previous = current

    distance = previous[len(right)]
    return distance if distance <= allowance else None
