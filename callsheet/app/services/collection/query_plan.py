"""Turning one title's identity set into the several queries a cycle runs (E03-S01).

The preview spends one call and asks the single best question (E02-S03). Collection is the
opposite trade: it runs every cycle, forever, and the whole point of a rich identity set is
that no one query finds all of the conversation. `"Lokesh Kanagaraj DC"` returned 20 of 20
relevant posts and *nothing* tagged `#DCFDFS` by someone who never named the director.

So a cycle fans out. That fan-out is what makes deduplication load-bearing from the very
first poll — the same popular post comes back on several variants — and it is also why the
variant that found a post is worth keeping (`mention_query_matches`).

Two rules shape what is built here:

* **Ordered by precision, then capped.** Variants are generated most-precise-first and cut
  at the configured ceiling, so raising or lowering the cap adds or removes the *weakest*
  queries rather than shuffling which ones run. A cycle's cost is variants x platforms, so
  the cap is a cost control and belongs in configuration, not in this file.
* **Deterministic.** The same identity set produces the same variants in the same order on
  every cycle, whatever order the studio typed things in. Attribution keys are stored, so a
  variant that renamed itself between cycles would look like a new term that suddenly
  started working.

Exclusions never appear. They disqualify a post rather than fetching one, and a query built
from one would collect precisely the contamination the studio asked to be rid of.
"""

import enum
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import structlog

from app.core.identity_terms import has_meaningful_content, normalize_term
from app.core.preview_query import build_anchored_query
from app.models.title import Title, TitleTerm, TitleTermType, identity_term_sort_key

_logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class QueryVariant:
    """One query a cycle runs, and the name its results are attributed to.

    `key` and `query` are deliberately different things. `query` is provider input and may
    change as the query builder improves — quoting, anchor placement, operators. `key` is
    what this variant is *called*, and it is what gets stored against every mention the
    variant finds. Storing the query string instead would mean improving the phrasing of a
    query silently orphaned a term's entire matching history.
    """

    key: str
    query: str
    source_term: str

    def __post_init__(self) -> None:
        if not self.key or not self.query:  # pragma: no cover — construction is internal
            raise ValueError("A query variant needs both a key and a query")


def build_query_variants(title: Title, *, limit: int) -> list[QueryVariant]:
    """The queries this title is collected with, most precise first, capped at `limit`.

    `title.terms` must already be loaded — this reads it, and the relationship is
    `lazy="raise"` precisely so an accidental lazy load inside a worker fails loudly
    instead of issuing a query per variant.
    """
    if limit <= 0:
        _logger.warning("collection.plan.no_variants", title_id=str(title.id), limit=limit)
        return []

    positive_terms = ordered_identity_terms(title)
    anchors = [term.value for term in positive_terms if term.term_type.is_anchor]

    variants = _deduplicate(_candidate_variants(title.name, positive_terms, anchors))
    capped = variants[:limit]

    if len(variants) > limit:
        _logger.info(
            "collection.plan.capped",
            title_id=str(title.id),
            available=len(variants),
            limit=limit,
        )
    _logger.debug(
        "collection.plan.built",
        title_id=str(title.id),
        variants=[variant.key for variant in capped],
    )
    return capped


def ordered_identity_terms(title: Title) -> list[TitleTerm]:
    """A title's positive identity terms, in a total order, sorted here rather than trusted.

    `Title.terms` declares the same `order_by`, but that only applies when the query
    actually loads the collection. It does not on the write path: a title's terms are
    assigned in memory by `TitleService`, and SQLAlchemy hands that list straight back
    instead of re-reading it. So the response to a POST — and any cycle running in the
    same session as a create — would plan against insertion order while an independent
    read planned against the sorted order.

    That is the same trap `TitleService.milestones_in_order` exists for (E02-S02), and it
    matters more here: this order decides which anchor leads the title's own query and,
    because the plan is capped, which variants get to exist. Sorting at the point of use
    costs nothing for a handful of rows and cannot be defeated by session state.

    Exclusions are dropped rather than sorted: they disqualify a post rather than fetching
    one, and a query built from one would collect the very contamination the studio asked
    to be rid of.
    """
    return sorted(
        (term for term in title.terms if not term.term_type.is_exclusion),
        key=identity_term_sort_key,
    )


def _candidate_variants(
    name: str, positive_terms: Sequence[TitleTerm], anchors: Sequence[str]
) -> Iterable[QueryVariant]:
    """Every query worth running, generated in descending order of precision."""
    # 1. The measured shape. One anchor beside the title's name is the query the live run
    #    scored 20/20 on, so it runs first and is the one variant a title always has.
    yield QueryVariant(
        key="name",
        query=build_anchored_query(name, anchors),
        source_term=name,
    )

    # 2. Hashtags. Second because an organic tag is the highest-signal thing a studio can
    #    declare — it is a term the audience chose — and it finds posts that name nobody.
    yield from _variants_for_types(
        positive_terms, anchors, name, (TitleTermType.HASHTAG,), style=_QueryStyle.BARE
    )

    # 3. Aliases, anchored exactly the way the name is. A regional or working title has the
    #    same namesake problem the real one does — "Drug Cartel" unanchored returns posts
    #    about actual drug cartels — so it gets the same person beside it.
    yield from _variants_for_types(
        positive_terms, anchors, name, (TitleTermType.ALIAS,), style=_QueryStyle.ANCHORED_TITLE
    )

    # 4. The remaining people, each paired with the title name. Last because they are the
    #    broadest: a director is attached to several films at once, so these bring in the
    #    most contamination per post found and are the first thing the cap should drop.
    yield from _variants_for_types(
        positive_terms,
        anchors,
        name,
        (TitleTermType.CAST, TitleTermType.DIRECTOR, TitleTermType.MUSIC_DIRECTOR),
        style=_QueryStyle.PERSON_WITH_TITLE,
        skip_first_anchor=True,
    )


class _QueryStyle(enum.Enum):
    """How a term becomes a query.

    Named on the band rather than inferred from the term type, because the three shapes
    are not a property of the term — they are a property of what the term *is to the film*.
    An alias and a cast member are both "not the title", and inferring from the type is how
    an alias silently ended up unanchored while the comment above it claimed otherwise.
    """

    # The term is already a claim of identity and stands alone. `#DCFDFS` has no namesake
    # to disambiguate, and demanding the director's name beside a tag is the opposite of
    # why people use tags.
    BARE = "bare"
    # The term names the film. It carries the film's namesake problem, so it takes the
    # film's treatment: an anchor person in front of it.
    ANCHORED_TITLE = "anchored_title"
    # The term names a person. The film's name goes beside them, which is the shape the
    # live run measured at 20 of 20 — the person first, the film second.
    PERSON_WITH_TITLE = "person_with_title"


def _variants_for_types(
    positive_terms: Sequence[TitleTerm],
    anchors: Sequence[str],
    name: str,
    term_types: tuple[TitleTermType, ...],
    *,
    style: _QueryStyle,
    skip_first_anchor: bool = False,
) -> Iterable[QueryVariant]:
    """Variants for one band of term types, in stored order within the band.

    `skip_first_anchor` drops the anchor that variant 1 already used. Running
    `"Lokesh Kanagaraj DC"` and then `"Lokesh Kanagaraj DC"` again would be paying twice
    for one query — the commonest shape by far, since most titles declare exactly one
    director.
    """
    leading_anchor = anchors[0] if anchors else None
    for term in positive_terms:
        if term.term_type not in term_types:
            continue
        if skip_first_anchor and term.value == leading_anchor:
            continue
        if not has_meaningful_content(term.normalized_value):  # pragma: no cover — refused at save
            continue
        yield QueryVariant(
            key=f"{term.term_type.value}:{term.normalized_value}",
            query=_query_for_term(term, name, anchors, style),
            source_term=term.value,
        )


def _query_for_term(
    term: TitleTerm, name: str, anchors: Sequence[str], style: _QueryStyle
) -> str:
    match style:
        case _QueryStyle.BARE:
            return term.value
        case _QueryStyle.ANCHORED_TITLE:
            return build_anchored_query(term.value, anchors)
        case _QueryStyle.PERSON_WITH_TITLE:
            return build_anchored_query(name, (term.value,))


def _deduplicate(variants: Iterable[QueryVariant]) -> list[QueryVariant]:
    """First occurrence wins, on both the key and the query text.

    Two checks rather than one, because they catch different mistakes. Repeated keys would
    corrupt attribution — the same term counted twice. Repeated *queries* under different
    keys are worse: the provider is paid twice for one page, and both keys are credited
    with finding what only one of them fetched. That happens whenever a studio enters the
    same string in two fields, which the identity set permits by design (a person can be
    both director and music director).
    """
    unique: list[QueryVariant] = []
    seen_keys: set[str] = set()
    seen_queries: set[str] = set()
    for variant in variants:
        normalized_query = normalize_term(variant.query)
        if variant.key in seen_keys or normalized_query in seen_queries:
            continue
        seen_keys.add(variant.key)
        seen_queries.add(normalized_query)
        unique.append(variant)
    return unique
