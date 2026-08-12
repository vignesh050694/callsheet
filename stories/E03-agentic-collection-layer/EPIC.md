# Epic E03 — Agentic Collection Layer

**Phase:** 1
**Source:** Concept note §2 (pivot evidenced), §5.2, §7 (unit economics), §11.3, §11.6

## Epic hypothesis

**We believe that** collecting through an agentic layer over Monid — rather than hand-built platform
connectors — and storing every raw payload verbatim
**will result in** four-platform coverage at roughly **$273 per title** across a six-month campaign,
with reprocessing costing nothing,
**We will know we are right when** a pilot title's measured collection cost per day stays within the
§7 model and at least one full pipeline re-run is served entirely from stored payloads.

## Why this epic exists

v0.1's blockers are gone at confirmed prices: X keyword search at **$0.0015 PER_CALL**, Instagram
hashtag/general search at **$0.003 PER_CALL**, Reddit at **$0.0015 PER_CALL**, YouTube comments at
**$0.0015 PER_CALL**. A live run returned 20 posts in **3.9 seconds for $0.0015** with a working
pagination cursor.

Access is settled. What this epic must get right is **cadence, cost discipline, and durability of the
raw corpus** — because analysis (E04) is the real budget risk and it must never force a re-collection.

## Personas served

- **P1 Production House** — indirectly: freshness, coverage, and "is it actually running?".
- **Internal Data Ops** — the operator persona who owns collection health and spend.

## Stories

| ID | Summary | Phase | Status | Commit |
|---|---|---|---|---|
| E03-S07 | Keep the collection agent's tool interface provider-agnostic | 1 | done | 8d36606 |
| E03-S04 | Store raw payloads verbatim and reprocess without re-paying | 1 | in-review | — |
| E03-S01 | Start collecting automatically on title creation, counting each post once | 1 | todo | — |
| E03-S02 | Shift polling cadence with the campaign phase | 1 | todo | — |
| E03-S03 | Backfill the conversation from before I signed up | 1 | todo | — |
| E03-S05 | See per-platform collection health and coverage gaps | 1 | todo | — |

**S06 was merged into S01** and its file deleted; its content lives on as S01's second scenario.
S01 already required a poll that spans every configured query variant, which is the exact condition
that makes deduplication load-bearing from the first poll — and with the dedupe key already built
in S07, what remained of S06 was a matched-variant list plus that fan-out, not a story on its own.

**S02, S03 and S05 stay separate**, each carrying value S01 does not. S02 is the cost lever
(release-week rates for release week only) and replaces S01's single default rate rather than
duplicating it. S03 is a different trigger with its own screen, cost estimate, and page-depth
honesty. S05 depends on S02's phases to define "stale", but that is a dependency, not shared work.
The seam between S01 and S02 is deliberately by user outcome, not by layer — each keeps the
dashboard surface it earns, since a UI-only "show the phase" story would deliver nothing alone.

**Delivery order deviates from the concept note's listing order.** S07 runs first because it *is* the
mention shape and the port: S01 ("collection starts on its own") has nothing to start without them,
and building it first would mean inventing the corpus schema inside a story about a trigger. S04
follows, then S01.

## Dependencies

- **Blocked by:** E02 (needs an identity set to query).
- **Blocks:** E04, E05, E08.
- **Coupled to:** E09 (cost governance rules are enforced inside this layer).

## Gate this epic is measured against

> Collection cost per title per day **within the §7 model** (~$0.225 per poll; ~$273 per title).

## Open items to resolve with Monid (concept note §11.6)

- Rate limits per key at surge cadence (48 polls/day).
- Server-side result caps on PER_RESULT endpoints.
- Provider substitution behaviour if an endpoint goes down.

## Out of scope

- Posting, replying, or any write action on any platform (explicitly out of scope for v1, §5).
- Platforms beyond X, Reddit, YouTube, and Instagram (Phase 4).

## Delivery log

**Branch:** `epic/E03-agentic-collection-layer` (branched from
`epic/E02-title-setup-identity-discovery`, which is not yet merged to `main` — collection
needs the title identity set that epic delivered)

- **E03-S07** — done · `8d36606` · 54 tests · 364 backend tests · `make check` green.
  Two review rounds. Nothing in `callsheet-ui/` was touched, so no frontend gate applies.

  **Started this epic out of listed order, and E02 is not finished.** E02-S04 (approve
  discovered aliases) and E02-S05 (exclude a contaminating term) are both blocked on a
  corpus that only E03 can produce, while E03 lists E02 as its blocker — a loop that only
  resolves from this side, since the identity set those two stories refine already exists
  (E02-S01–S03 are `done`). Within E03, S07 runs before S01 because it *is* the mention
  shape and the port; building "collection starts on its own" first would have meant
  inventing the corpus schema inside a story about a trigger.

  What landed: a `CollectionSource` port speaking platform + query + page, never a vendor
  path; an endpoint catalogue keyed internally, carrying provider and price model, with
  per-platform primary/alternative routing so a switchover is one environment variable;
  one adapter per endpoint owning **both** directions (request *and* response), because
  tikhub takes `keyword` in a query string and pages on a cursor while apify takes
  `searchTerms` in a body and has none — a caller that built the request could not stay
  provider-agnostic; and two tables, `mentions` (the corpus, with **no provider column**,
  so no chart can split a title's trend at the moment operations swapped endpoints) beside
  `mention_raw_payloads` (what was paid for, verbatim, carrying the provenance the
  normalised row refuses to hold).

  **Both adapters are mapped against live captures, not vendor documentation.** Two paid
  calls were made with explicit approval — tikhub PER_CALL $0.0015 for 20 posts, apify
  PER_RESULT capped at 5 for $0.003, $0.0045 total — and both responses are committed as
  fixtures. They overlap on tweet `2087233047506866356`, which is what makes "one
  continuous trend" testable rather than asserted: collected through tikhub then apify,
  the title ends with one series and no duplicate for that post.

  The captures paid for themselves in defects avoided. X labelled Tamil script `et`
  (Estonian), romanised Tamil `in`, and code-mixed Tamil-in-Latin `en` — **5 of 20
  mislabelled**, which is why the field is `platform_reported_language` and why nothing
  filters on it. tikhub returns `views` as a *string* while every sibling count is an int.
  The timestamp is X's legacy format, not ISO. `&amp;` arrives HTML-escaped. tikhub
  returns no permalink so one is derived, while apify returns a real URL. And one apify
  item held the entire 3,900-character post in `text` while its `fullText` was truncated
  to 272 characters — the reverse of what the names imply, so the adapter takes whichever
  is longer.

  Round 1 found two real defects, both of which a green suite was hiding.
  **Nothing was ever committed**: `CollectionService` flushed but never called
  `session.commit()`, though `app/db/session.py` states commits are the service layer's
  call and every other service obeys it. A run reported `stored=20`, closed the session,
  and left the database empty — losing a payload that had already been paid for, which is
  the one thing this epic exists to prevent. All 355 tests passed anyway, because
  `conftest`'s `db_session` fixture hands every call the same open, uncommitted session,
  so a read-after-write always succeeds whether or not a commit happened. **No test built
  on those fixtures could ever have caught it.** The regression test therefore builds its
  own engine and two independent sessions over a file-backed database, and was confirmed
  sensitive by deleting the commit and watching it fail.
  Second: **unreadable items accumulated forever.** The service read the post id off the
  mention, which is `None` when normalisation fails, so a broken payload matched nothing
  in the known-ids set and was re-inserted on every overlapping poll — and polls overlap by
  design. Adapters now expose `read_external_id` separately from `to_mention`, because
  "can I identify this item" and "can I fully read it" fail independently. Three identical
  polls now leave one row that keeps the vendor id and the failure reason, so E03-S04 can
  re-read it without paying again.
  Round 2 passed, verifying both fixes by re-injecting each bug and watching the specific
  test fail, and confirming model/migration agreement with `alembic check` against a real
  Postgres ("No new upgrade operations detected").

  Deliberate scope calls, both endorsed by the reviewer: **no HTTP transport** —
  `MonidTransport` is a seam whose default binding refuses with a 503, because run polling
  and spend controls are E03-S01 and E09, and an untested client behind an interface whose
  purpose is trustworthiness would be exactly the fiction it exists to prevent; and **no
  API route** — the story's persona changes configuration rather than making requests, and
  E03-S01 supplies the trigger.

  Known limits, recorded rather than hidden:
  - An item with **no readable id at all** still cannot be deduplicated and accumulates a
    row per poll. Tested as a limit, and logged as `collection.normalize.unidentifiable`
    at error, because an adapter that cannot find the provider's own primary key needs a
    human rather than a retry. Collection health (E03-S05) is where it should surface.
  - A page commits as one transaction, so a genuinely concurrent double-poll of the same
    title could hit the `mentions` unique constraint and roll back a whole page including
    its new items. Not reachable today — no scheduler exists — but it is **E03-S01's to
    handle** when one does (recorded against E03-S02 before the scheduler was placed in S01;
    S02's surge cadence is where it stops being theoretical).
  - `longest_text` is exercised on synthetic divergent input. The real diverging item was
    excluded from the committed fixture for size; the fixture says so in its own
    `_capture.note`.
  - Only X has adapters. Instagram, Reddit and YouTube are catalogued, priced, and routed
    in configuration, and resolving them fails loudly rather than collecting nothing.
