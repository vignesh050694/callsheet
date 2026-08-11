"""Building the single query a preview runs (E02-S03).

The live run settled the shape: `"Lokesh Kanagaraj DC"` — one person's name beside the
title's — returned 20 of 20 relevant posts, while the bare name returns its namesakes.
So the preview asks the same question the collection layer will, in the form that was
actually measured, rather than a cheaper approximation that would make the sample
unrepresentative of what the studio is about to buy.

One query, not one per term. A preview is a single call by design (concept note §7,
cost-control rule 2), and the anchored form is the one worth spending it on.
"""

from collections.abc import Sequence

# The whole identity set does not fit in one useful query — past a couple of anchors the
# results narrow to posts that name everyone at once, which is not what collection does.
MAX_ANCHORS_IN_QUERY = 1


def build_anchored_query(name: str, anchor_terms: Sequence[str]) -> str:
    """Quotes the title name, prefixed by an anchor when there is one.

    The quotes matter: an unquoted multi-word name is matched word by word, so
    "Vaaranam Aayiram" would collect every post containing either half.
    """
    leading_anchors = list(anchor_terms[:MAX_ANCHORS_IN_QUERY])
    phrase = " ".join([*leading_anchors, name])
    return f'"{phrase}"'
