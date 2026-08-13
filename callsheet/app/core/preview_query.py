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


def build_anchored_query(
    name: str, anchor_terms: Sequence[str], *, name_is_self_sufficient: bool
) -> str:
    """Quotes the title name, and adds an anchor beside it only when the name needs one.

    The quotes matter: an unquoted multi-word name is matched word by word, so
    "Vaaranam Aayiram" would collect every post containing either half.

    Two corrections live here, both measured against live search rather than reasoned about.

    **The anchor sits outside the quotes.** Inside them it is not an anchor at all, it is a
    demand that the two names appear as one contiguous phrase — `"Adithya Kathir Mr Bhaarath"`
    matches only a post that literally writes those words in that order, and returned 0 results
    where `"Mr Bhaarath"` returned 20 of 20 relevant. Outside the quotes it is a second required
    term, which is what "one person's name beside the title's" was always meant to be.

    **A self-sufficient name takes no anchor.** `"Lokesh Kanagaraj DC"` — the run this function
    was originally shaped by — worked because *DC* is two characters and means nothing on its
    own, so the anchor was carrying the entire query. A distinctive name is the opposite case:
    every anchor added to it is another condition a real post has to satisfy, and posts about a
    film rarely name a specific cast member. The caller decides which case it is, using the same
    rule that decides whether the name may be collected unanchored at all (E02-S01), so the
    query and the setup form can never disagree about what counts as a name that stands alone.
    """
    quoted_name = f'"{name}"'
    if name_is_self_sufficient or not anchor_terms:
        return quoted_name
    leading_anchors = list(anchor_terms[:MAX_ANCHORS_IN_QUERY])
    return " ".join([quoted_name, *leading_anchors])
