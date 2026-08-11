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
| E02-S03 | Preview live sample results before committing setup | 1 | done | — |
| E02-S04 | Review and approve discovered alias suggestions | 1 | todo | — |
| E02-S05 | Exclude a contaminating term from a title's results | 1 | todo | — |
| E02-S06 | Reject invisible characters as anchor terms | 1 | todo | — |
| E02-S07 | Measure title length by grapheme, not code point | 1 | todo | — |

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

- **E02-S03** — done · 65 tests · 310 backend tests · `make check` + `npm run check` + build green.
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
