"""Building the query a title is searched with — by the preview and by collection (E02-S03).

The live run settled the shape: one person's name beside the title's returned 20 of 20
relevant posts, while the bare name returns its namesakes. So the preview asks the same
question the collection layer will, in the form that was actually measured, rather than a
cheaper approximation that would make the sample unrepresentative of what the studio is
about to buy.

One query, not one per term. A preview is a single call by design (concept note §7,
cost-control rule 2), and the anchored form is the one worth spending it on.

**Each part is quoted on its own.** That is the whole substance of this module and it was
got wrong once, so it is worth stating plainly: `"Rio Raj" "Ram in Leela"` asks for both
phrases somewhere in the post, which is what "a post about my film that also names someone
from it" means. `"Rio Raj Ram in Leela"` — the same words inside one pair of quotes — asks
for those five words *adjacent, in that order*, which essentially nobody writes, and the
query returns nothing at all.

The mistake survived because of the film it was measured on. The capture was taken for a
title called `DC` with `Lokesh Kanagaraj` attached, and "Lokesh Kanagaraj DC" happens to be
a phrase Tamil film Twitter writes contiguously — director then title is an ordinary
construction there. One phrase and two phrases return nearly the same posts for that one
input, so a real 20-of-20 capture endorsed a rule that is wrong for every multi-word title.
It is a good reminder that a live capture validates the example, not the generalisation.
"""

from collections.abc import Sequence

# The whole identity set does not fit in one useful query — past a couple of anchors the
# results narrow to posts that name everyone at once, which is not what collection does.
MAX_ANCHORS_IN_QUERY = 1

_PHRASE_DELIMITER = '"'


def build_anchored_query(name: str, anchor_terms: Sequence[str]) -> str:
    """The title's name as one phrase, preceded by an anchor's name as another.

    Order is the measured one — the person first, the film second — and it is kept even
    though two quoted phrases are an unordered AND on every platform this product queries.
    Nothing depends on it, and matching what was measured costs nothing.
    """
    parts = (_searchable(part) for part in (*anchor_terms[:MAX_ANCHORS_IN_QUERY], name))
    # Filtered *after* cleaning, not before. A term of nothing but whitespace is falsy only
    # once it has been stripped, and an unstripped one would survive the filter and render
    # as an empty `""` phrase — which every platform reads as a literal empty string and
    # nothing matches. Callers all reject blank terms long before here, so this is the
    # backstop for the caller written next year, not for one that exists today.
    return " ".join(f"{_PHRASE_DELIMITER}{part}{_PHRASE_DELIMITER}" for part in parts if part)


def _searchable(term: str) -> str:
    """One term with any quotes of its own removed, ready to be wrapped in quotes.

    A studio that types `Ram "in" Leela` would otherwise close the phrase early and hand
    the platform a malformed query — which fails as *fewer results*, never as an error, so
    nothing downstream would report it. Dropping the character is the honest repair: the
    words still have to appear together, and no interior quote a film's name contains is
    load-bearing to finding it.
    """
    return term.replace(_PHRASE_DELIMITER, "").strip()
