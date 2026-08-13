# Epic E02 — Title Setup & Identity Discovery

**Phase:** 1
**Source:** Concept note §5.1, §6.1 (entity match validated at 20/20), §11.1, §11.5

## Epic hypothesis

**We believe that** making title identity rich at setup *and* continuously discovered from the corpus
**will result in** entity-match precision holding at or above 0.85 on anchored queries while catching
organic hashtags the studio never declared,
**We will know we are right when** a title's approved alias set contains at least one term the
production house did not enter at setup, and precision does not drop after that term is added.

## Why this epic exists

The live *DC* run proved two things at once:

1. The anchored query `"Lokesh Kanagaraj DC"` returned **20 of 20 relevant posts** — rich identity works,
   and justifies asking the production house to do real setup work.
2. Twenty posts alone surfaced seven organic hashtags (`#DCthemovie`, `#DCFDFS`, `#DCPublicReview`,
   `#DCTheBloodyValentineFromAugust7`, …) and misspelt name variants ("Kankaraj"). The identity set
   must be **discovered, not just declared**.

It also surfaced contamination inside an anchored query (`#DC #DareDevil` — the predicted DC Comics
bleed), which is why exclusion terms are a first-class setup control, not a support ticket.

## Personas served

- **P1 Production House** — does the setup, approves the suggestions.
- **P2 Artist** — corrections made at invite acceptance (E01-S04) flow into the same alias set.

## Stories

| ID | Summary | Phase | Status | Commit |
|---|---|---|---|---|
| E02-S01 | Create a title with a rich identity set | 1 | done | 7c4777c |
| E02-S02 | Anchor the title to a release date and campaign milestones | 1 | done | 1b91add |
| E02-S03 | Preview live sample results before committing setup | 1 | done | dcca668 |
| E02-S04 | Review and approve discovered alias suggestions | 1 | done | 109dd56 |
| E02-S05 | Exclude a contaminating term from a title's results | 1 | done | 8924e6e |
| E02-S06 | Reject invisible characters as anchor terms | 1 | done | 2fde760 |
| E02-S07 | Measure title length by grapheme, not code point | 1 | in-progress | — |

## Dependencies

- **Blocked by:** E01 (a title belongs to an org) — **satisfied**. Organizations and memberships
  landed in E01-S01 (`a708c43`) and E01-S02 (`331ba42`), which is all a title needs to hang off.
  E01's remaining stories (S03–S06) are themselves blocked on titles from this epic, so they run
  after it rather than before.
- **Blocks:** E03 (nothing to collect without an identity set), E05 (pre/post release split needs §E02-S02).

## Gate this epic is measured against

> Entity-match precision on anchored query **≥ 0.85** — *provisionally met at 1.00* (concept note §9).

## Out of scope

- Automatic title creation from a trade announcement feed.
- Comparable-title benchmarking (Phase 4).

## Delivery log

**Branch:** `epic/E02-title-setup-identity-discovery` (branched from
`epic/E01-organizations-access-membership`, which is not yet merged to `main` — a title needs
the organizations and memberships that epic delivered)

- **E02-S01** — done · `7c4777c` · 97 tests · `make check` + `npm run check` green · both READMEs
  updated. Four review rounds; seven real bypasses of the anchor rule found and fixed:
  zero-width characters counting as anchor terms; single-hash stripping breaking hashtag dedupe;
  blank-rendering Hangul/Braille characters classified as letters or symbols; `len()` counting
  code points so combining marks or a ZWJ emoji padded one glyph past the threshold; unbounded
  term strings returning 500 instead of 422; and `Mc` spacing vowel signs excluded from the
  visible count. Shipped by decision with two known holes in the anchor rule, both filed:
  **E02-S06** (variation selectors U+FE00–FE0F are category `Mn`, so they pass as invisible
  anchor terms) and **E02-S07** (length is counted per code point, so `सीता` and `काका` are
  accepted bare while `राधे` — the same two aksharas — is refused). Neither affects the identity
  set itself, only the rule guarding short names. The reviewer ruled that refusing `राधे` is
  correct; the defect is that equally short titles are not refused.

- **E02-S02** — done · `1b91add` · 75 tests · 245 backend tests · `make check` + `npm run check` + build green ·
  both READMEs updated. Two review rounds.
  Round 1 found an **unhandled 500 from NFKC length expansion**: `max_length` was checked on the
  raw request string, but stored values are NFKC-normalised first and NFKC expands — 120 copies of
  `ﬁ` clear a 120-character bound and become 240. The oversized value was written, then the
  response schema re-checked the same limit and raised. On SQLite the row committed before the
  crash, so every later read of that title also failed: the title became permanently unreadable.
  The reviewer found it on milestone names; the same path is used by the title name and every
  identity term, so **E02-S01 had shipped the same defect** and it was fixed on all four surfaces
  via `TitleService._ensure_fits`, which bounds the value after normalisation.
  Round 2 found that same-day milestones had **no deterministic order** — date alone is not a
  total order, and retyping a label issues an UPDATE that can relocate the row, swapping two
  markers between reads. Fixed with `(occurs_on, normalized_name)`, which the unique constraint
  guarantees never ties.
  Also fixed before review: milestone replacement tripped its own unique constraint, because
  SQLAlchemy emits INSERTs before orphan DELETEs in one flush, so every kept beat collided with
  its outgoing row (now diffed rather than replaced, which also keeps milestone ids stable); and
  the relationship's `order_by` does not apply when the collection is already loaded in the
  session, so POST and PUT returned milestones in insertion order.
  The story's rendering criteria — a divider on every time-series view and a pre/post toggle on
  the dashboard — were **not built and could not be**: there is no collection layer (E03) and no
  dashboard (E04/E05). What landed is the anchor, the read-time boundary shared by both projects,
  and a standalone `ReleaseTimeline`. Both reviewers were asked to judge that call and both
  endorsed it. Known holes shipped by decision: variation selectors pass as milestone names
  (**E02-S06**, scope widened to cover this second surface) and schedule edits have no optimistic
  concurrency, so simultaneous owners silently overwrite each other.

- **E02-S03** — done · `dcca668` · 65 tests · 310 backend tests · `make check` + `npm run check` +
  build green.
  **Shipped by decision over a `changes-requested` verdict**, with the open finding named below.
  Three review rounds, each finding a real defect, all in the same place: **what makes two identity
  terms "the same word" in this corpus.**
  What landed: a `PreviewSearch` port carrying the cost rule in its shape — one call, one page, a
  hard cap of 20 (concept note §7 rule 2) — whose default binding is unconfigured and answers 503
  rather than inventing a sample; the anchored query in the form the live run measured
  (`"Lokesh Kanagaraj DC"`); per-post match evidence; `TitleTermType.EXCLUSION` seeded by marking a
  post "not my title", kept out of `collection_terms` because it is the opposite instruction; and
  the setup panel. The **Monid-backed adapter is deliberately not here** — it plugs into the port
  with E03, so no environment returns real posts yet. No migration was needed for the new enum
  member: `native_enum=False` with SQLAlchemy 2.0's `create_constraint=False` compiles to a plain
  `VARCHAR(14)`, verified against the generated Postgres DDL.
  Round 1: `\w`-based hashtag extraction truncated `#தமிழ்சினிமா` to `#தம` — `\w` excludes
  categories Mn and Mc, which is every Indic vowel sign and virama. Fixed by deciding word
  boundaries in Python.
  Round 2: that fix was half-done. Joiners counted as part of a word but still counted for
  *equality*, so a hashtag declared without a ZWNJ and the same visual word carrying one were
  unrelated strings — the preview offered the studio's own hashtag back as contamination and the
  self-exclusion guard let it through. Fixed with `joiner_folded`, a comparison-only fold.
  Round 3, **shipped open**: that fold is over-broad. ZWJ is not only a rendering hint, it is also
  what fuses emoji into one grapheme, so `joiner_folded` collapses `👨‍👩‍👧` and `👨👩👧` (verified).
  A declared identity term containing an emoji ZWJ sequence can therefore be silently dropped at
  dedupe, fabricate a match against a post that never contained it, or have a legitimate exclusion
  refused. Judged low impact and shipped: emoji are vanishingly rare as film identity terms, and
  nothing consumes exclusions or collection terms until E03 — whereas reverting the fold would
  restore the round-2 defect, which is common on this corpus. The likely fix is to scope the fold
  to joiners between letters or marks and leave joiners between symbols alone, but "when has a
  studio already declared that term?" is a rule about meaning and wants a human ruling.
  Also shipped open, both cheaper: the setup panel keeps chosen exclusion terms in page state
  across an identity-set edit or a second preview run, so a term can reach `TitleCreate.exclusions`
  with no visible origin (listed and removable, but unattributed); and
  `TitlePreviewService._build_draft` dedupes on the bare normalised form while the save path folds,
  a drift between the two paths that downstream folding currently masks.

- **E02-S04** — done · `109dd56` · 9 tests · 538 backend tests · `make check` + `npm run check` + build green.
  Two review rounds. What landed: a corpus miner (`app/core/alias_candidates.py`) that reads a
  title's own stored mentions and returns two kinds of candidate — hashtags the identity set does
  not claim, and near-miss spellings of terms it does — ranked by post count with a total-order
  tiebreak on the folded value; an `AliasDiscoveryService` where suggestions are *derived on read*
  and only decisions are stored; and the owner-gated setup screen.
  **Misspellings are mined per word, not per phrase.** The live corpus carried "Kankaraj", never
  "Lokesh Kankaraj", so each word of a declared multi-word name six characters or longer is also a
  target on its own and reports the whole name as what it resembles. Comparing only the full phrase
  would have missed the commonest form of the mistake entirely and satisfied the story on paper.
  **Approving spends nothing, structurally.** `AliasDiscoveryService` is constructed without a
  collection source, the same guarantee `ReprocessService` gets (E03-S04): the absence of the
  dependency is the rule. Retroactive credit is written as `MentionQueryMatch` rows carrying a new
  `MatchSource.RETROACTIVE`, kept apart from collection hits because counting them together would
  credit a term with fetching posts it never fetched.
  Round 1 found the consequence of that separation: `existing_pairs` keys only on
  `(mention_id, query_variant)`, so once a term ran as a real paid query and returned a post it had
  already been credited with retroactively, the insert was correctly skipped and the row stayed
  `RETROACTIVE` for the life of the campaign — permanently undercounting exactly the terms
  discovery found. Fixed with `promote_retroactive_to_collection`, called from the cycle's
  crediting step; `first_matched_at` is deliberately left alone, and its docstring was reworded
  from "first returned" to "first credited" so the column carries one meaning rather than two.
  Round 1 also flagged `restore_rejected` as a mutating endpoint shipped untested; round 2 covered
  it, including the cross-title scoping guard. Round 2's only finding was two over-length lines in
  the new test file failing `make check` — the orchestrator had linted `app/` rather than the whole
  tree, which is what `make lint` actually runs. Fixed and the real gate re-run.
  The migration was applied and rolled back against live Postgres by the reviewer, including a
  check that the enum persists as the member *name*.
  Known limitations, shipped by decision: the suggestion read scans the 2,000 most recent mentions
  rather than the whole corpus, so on a campaign larger than that every count describes the recent
  window — the response returns `scanned_mentions` beside `corpus_size` and the screen says which,
  rather than implying full coverage. `AliasApprovalOutcome.has_spent_nothing` is asserted nowhere
  (its `ReprocessService` sibling is). And an undo for rejections was built though the story does
  not ask for one: "never re-suggested" is permanent, decided from one screenful of evidence in
  week one, and the alternative to a button is a support ticket.

- **E02-S05** — done · `8924e6e` · 9 tests · 547 backend tests · `make check` + `npm run check` + build green.
  Two review rounds. What landed: `TitleExclusionService` (measure, apply, lift), a narrow
  mentions feed to decide from, and the `excluded_by_term` marker on `mentions`.
  **The confirmation is on a number, not a string.** `#DC` and `#DareDevil` are
  indistinguishable as text and remove wildly different shares of a corpus, so the impact is
  measured over the *whole* corpus before the rule exists, quoted with sample posts, and
  flagged when it would remove everything. That is the story's "show the removal count before
  confirming", and it is the only thing separating a good rule from one that silently empties
  a title.
  **Marked, never deleted.** The row was paid for and the judgement is reversible, so the rule
  sets `excluded_by_term` and lifting it flips the flag back — no re-collection. Every
  aggregate in `MentionRepository` now filters marked rows, the cadence baseline included, so
  a franchise collision the studio disowned cannot buy surge polling. The two that deliberately
  do not filter are `count_for_title_including_excluded` (a statement about coverage, not the
  film) and `ids_by_external_id` (a query genuinely did return the post). Lifting one of two
  rules re-credits the post to the survivor rather than handing it back.
  **A mentions feed had to be built.** The story's Givens require one — "every post in the feed
  has a 'Not my title' action" — and E05's dashboard does not exist. What landed is the narrow
  version: posts, why each matched, and what could exclude it. Segmentation, language detection
  and sentiment stay E04/E05's.
  Round 1 found the access gate on that feed was wrong, and the justification written into its
  docstring was wrong with it. It used `require_owning_organization` on the reasoning that both
  shared roles have narrower views. False for the agency: E01-S05's scope line is "reads and
  exports this title only" — the owner's view narrowed to one title, not narrowed in content —
  so an agency clicking the Mentions link got a 404 on a title they can demonstrably see. Now
  `require_readable`, plus an explicit refusal for the one role whose promise really is
  narrower: a tagged artist sees "only mentions that also mention them", that filtered view
  needs E06's artist terms, and all three alternatives were bad — the whole feed over-shares, a
  404 denies a title they accepted an invitation to, and only a 403 naming the limit is true.
  Round 2 confirmed the fix and established that an artist who is *also* in an agency holding a
  grant resolves to their artist role structurally, not by luck: the check constraints stop
  either lookup returning the other's rows.
  Known limitations, shipped by decision: the artist-scoped feed is refused rather than built
  (E06); the impact scan and the sweep both walk the whole corpus in Python rather than SQL,
  because "does this term appear as a whole word" is not a `LIKE`, which is right but is linear
  in corpus size on a screen a studio opens repeatedly; and an exclusion applies to one title
  only — account-level exclusion is E04-S03 and was deliberately not built.

- **E02-S06** — done · `2fde760` · 22 cases in 5 tests · 569 backend tests · `make check` + `npm run check` green.
  **One review round, passed first time** — the only story in this epic that has.
  The story asked for a fix that asks "does this render anything" rather than one that adds
  `Mn` to a category list, and that is what landed: `_renders_on_its_own` answers False for
  anything invisible *and* for any Unicode mark, on the reasoning that a mark is not a
  character in its own right — it modifies the one before it, and with nothing before it there
  is nothing to modify. Variation selectors are `Mn`, which is why they got through; so would
  the next neighbour in that family, and now none of them do.
  One predicate, three callers, two bugs closed: a term of one variation selector satisfied the
  anchor rule *and* painted an unlabelled marker on the campaign timeline. E02-S02 left a
  characterisation test pinning the milestone half with an instruction to rewrite it rather
  than delete it when this story landed; it was rewritten to assert 422, and strengthened while
  it was open.
  `visible_length` was deliberately not touched — that is E02-S07, and changing it here would
  have silently altered which titles need an anchor at all.
  The reviewer swept every caller for over-rejection, since this widens a refusal: the two call
  sites that pass already-normalised values apply the same predicate at save and at query time,
  so there is no split brain, and no real single-word term in any script is entirely marks
  (abugidas need a base consonant).
  **Carried, pre-existing:** the client mirror is stricter than the server on private-use
  characters — JS `\p{C}` spans `Co/Cs/Cn` while the server checks `Cc/Cf/Zl/Zp/Zs`, so
  `U+E000` blocks the form's submit button on a value the server would accept. Confirmed by the
  reviewer, unchanged by this story, and left alone rather than widened into it.
