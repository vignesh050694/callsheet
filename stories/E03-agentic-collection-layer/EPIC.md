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
| E03-S04 | Store raw payloads verbatim and reprocess without re-paying | 1 | done | 475ff34 |
| E03-S01 | Start collecting automatically on title creation, counting each post once | 1 | done | fa67410 |
| E03-S02 | Shift polling cadence with the campaign phase | 1 | done | 14c15b0 |
| E03-S03 | Backfill the conversation from before I signed up | 1 | done | 3e47d7a |
| E03-S05 | See per-platform collection health and coverage gaps | 1 | done | 9007554 |

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

**Epic status:** complete — 6/6 stories on `epic/E03-agentic-collection-layer`, awaiting merge.
The branch is not on `main` and neither is its parent, `epic/E02-title-setup-identity-discovery`.
Gate (collection cost per title per day within the §7 model) is **projected, not measured**:
`cadence_cost.py` computes $271.80 from the cadence windows E03-S02 derived, and asserts it in a
test, but that is arithmetic over list prices. Measuring it against a provider invoice on a real
title is E09's, and has not been run.

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

- **E03-S04** — done · `475ff34` · 40 tests · 404 backend tests · `make check` green.
  Two review rounds. Nothing in `callsheet-ui/` was touched.

  What landed: `mention_analyses`, keyed `(mention_id, pipeline_version)` so a re-run is
  **additive** — the previous version's verdicts survive, the dashboard keeps reading the
  version it trusts while a long re-run proceeds, and rolling back a bad model is a change
  of which version is read rather than another pass over the corpus; a `MentionAnalyzer`
  port whose default binding refuses (E04 owns what analysis *says*, this story owns when
  it runs and how its output is versioned); a reprocess that re-reads each mention from its
  stored payload through today's adapter, making a mapping fix retroactive; and
  `make reprocess title=<uuid> [from=] [until=]`.

  **The zero-spend guarantee is structural, not a policy.** `ReprocessService` is
  constructed with no `CollectionSource` and no transport, so there is no path from it to a
  provider — a guarantee that survives people who never read the docstring. Verified end to
  end by deliberately breaking the adapter, collecting (20 payloads stored, 0 mentions),
  then recovering all 20 into mentions with **zero new provider calls**.

  Found in Stage 1 before review: the first reprocess reported `remapped=20` when nothing
  had changed. SQLite returns `posted_at` naive while adapters produce tz-aware datetimes,
  and `!=` between them is silently unequal — unlike `<`, which would at least raise. Every
  run would have dirtied every row and made the count noise, exactly where someone relies
  on it to tell them whether a mapping fix did anything.

  Stage 2 found the `unreadable` counter was **unreachable**. It keyed off
  `payload.normalization_error`, which collection only sets when a payload has no mention —
  and a reprocess walks the mentions table, so every payload it sees starts with that field
  null. A payload that went bad was neither remapped nor counted; it vanished into
  `examined`. Root cause was a boolean return collapsing "nothing moved" and "cannot be read
  at all". Now a four-way outcome.

  Review round 1 found five, of which one was serious: **the corpus walk could silently skip
  rows.** It read its keyset cursor from `batch[-1].posted_at` *after* `_remap` had rewritten
  that field — and correcting a timestamp is precisely what a reprocess exists to do. A run
  examined 5 of 10 mentions and reported success. The first fix (capture the cursor before
  yielding) stopped the skip and revealed `examined=11 of 10`: a *repeat*, because a shifted
  row now sorted past the cursor. The real defect was one level down — **the walk was ordered
  by a column the walk itself mutates.** It now pages by `Mention.id`, assigned once and never
  changed. The existing multi-batch test could not have caught this: it built payload-less
  mentions, so `_remap` never ran. Batching and remapping were each tested, never together.
  Also fixed: the no-adapter path collapsed back into `UNCHANGED` (now `UNVERIFIABLE`, its own
  counter — a configuration problem, not a data problem, and the fix differs); a single commit
  at the end of a six-week run discarded every repair and verdict on a late failure (now
  per batch, so a crash resumes); `spent_nothing` renamed for the boolean-naming convention;
  and `delete_for_title_and_version`, "the undo for a bad model run", was untested.
  **The no-route call from S07 did not transfer, and the reviewer was right to say so:** S07's
  persona changes a config value and needs no invocation path, whereas this persona must
  *trigger* a parametrised action. Hence the CLI.
  Round 2 passed, verifying the fixes by mutation — disabling the per-batch commit made the
  resumability test fail, confirming it is genuinely sensitive — and confirming model/migration
  agreement with `alembic check` against real Postgres.

  Known limits, recorded rather than hidden:
  - The id cursor is a random UUIDv4, so it is not time-ordered. A mention inserted by a
    *concurrent* process mid-walk, with a UUID sorting below the advanced cursor, would be
    missed by that run and picked up by the next one. Unreachable today — there is no poller
    until **E03-S01** — and it is that story's to consider alongside the concurrent
    double-poll defect it already inherited.
  - The story's "the dashboard reflects the new results" cannot complete end to end yet:
    with the shipped default binding a real trigger refuses at the analysis step. That is
    **E04**, and the refusal is clean — remap has run, nothing is left half-persisted.
  - Reprocess re-reads through whichever adapter serves the endpoint *today*. A payload whose
    endpoint has no adapter is reported `unverifiable` rather than silently passed over.

- **E03-S01** — done · `fa67410` · 58 tests · 462 backend tests · `make check` + `npm run check` +
  build green. **Three review rounds**, each finding a real defect in a different area.

  What landed: `collection_runs`, a polling queue in the database rather than a timer in a
  process, because a title whose next poll vanished with a deploy looks exactly like a title
  nobody is talking about. The first cycle is queued **inside the transaction that creates
  the title** — enqueuing after the commit leaves a window in which a title exists with
  nothing owed to it, and that state is not visibly broken: full identity set, empty
  dashboard, nothing scheduled to fill it. `TitleService` now takes the scheduler as a
  required constructor argument, so that state cannot be reached by forgetting to wire
  something up. Alongside it, `mention_query_matches` keeps the half of the fan-out that
  deduplication destroys — crucially crediting a variant for posts it found that were
  *already known*, since a popular post is stored by whichever query ran first and the other
  three found it just as genuinely. Cadence sits behind a `CadencePolicy` with one binding in
  `deps.py`; nothing else multiplies a rate by anything, which is the seam E03-S02 needs.

  **The query plan was wrong twice, in ways no acceptance criterion named.** Aliases were
  built unanchored — a bare `"Drug Cartel"` collects posts about actual drug cartels, the
  exact namesake problem the anchor rule exists to prevent, against an epic whose gate is
  entity-match precision. The cause was the query shape being *inferred from the term type*
  inside a helper whose caller silently omitted an argument; an alias and a cast member are
  both "not the title", so the type alone could never separate them. Replaced with an
  explicit `_QueryStyle` per band. Then the plan turned out not to be deterministic at all:
  `Title.terms` had no `order_by`, so DB row order decided which anchor led the query and,
  because the plan is capped, which variants existed. A reviewer reproduced a variant set
  changing with nothing changed by the studio — which E02-S04 would read as terms
  spontaneously starting and stopping working. This is the same defect E02-S02 already fixed
  on `milestones`; `terms` never got the treatment, and this story is what made it matter.
  The fix needed two layers, because a relationship's `order_by` does not apply when the
  collection is already loaded — the write path assigns `title.terms` in memory. Fixing that
  then broke an E02-S02 test that asserts the identity set is byte-identical across a
  schedule edit: the API had been serialising insertion order. `identity_term_sort_key` is
  now defined once and used by the relationship, the API response, and the query plan.

  **Four bugs of one class, in one file.** After `session.rollback()` every ORM instance is
  expired, and reading an attribute is synchronous Python that must issue a query — which an
  async session cannot do. Each occurrence turned a handled failure into an unhandled
  `MissingGreenlet`: in the log line reporting a cycle's failure; in the result built after
  the successor-queuing rollback; in the loop variable of the *next* run in the batch, whose
  instance a neighbour's rollback had expired. The last one is the general lesson — a
  rollback anywhere poisons every object in the session, including ones the failing code
  never touched — and it is why `run_due_cycles` now iterates ids and reloads each run inside
  its own iteration. Isolation had to re-establish state, not merely catch.

  Review round 1 also found a run could be left `RUNNING` forever, which is the worst state
  in this table because all three of its readers lie: `claim_due` only selects `QUEUED` so
  nothing revisits it, `has_pending_for_title` counts it as owed so no successor is queued,
  and `is_stalled` reads `False` so the dashboard reports the title as healthy. One
  misconfigured title stranded a healthy one that never ran. `_finish` now commits the closed
  run *before* queuing its successor — an ordering the new partial unique index forces, since
  a `RUNNING` row occupies its title's slot, and also the safer failure mode: closed with no
  successor is visibly stalled, which is true, whereas the atomic version rolls back into
  invisible. Round 1 also found the "one pending cycle per title" guarantee was a check
  followed by an insert, which two processes both win;
  `uq_collection_run_one_pending_per_title` now enforces it, verified on SQLite and Postgres.

  **The suite could not detect a missing commit.** A reviewer deleted every `commit()` from
  `CollectionRunService` and all 40 tests still passed — the same defect class the E03-S07
  entry above records, and for the same reason: `conftest`'s `db_session` hands every call one
  open session, so a read-after-write succeeds whether or not anything committed. Section 2's
  core assertion is now durable over two independent sessions, and deleting the commits fails
  it.

  Round 3 passed, having reset a local Postgres and run all eight migrations from scratch
  (`alembic check` clean), tested the partial index with raw SQL independent of the suite, and
  run the whole suite in reverse file order to prove the structlog-manipulating test leaks no
  global state.

  Known limits, recorded rather than hidden:
  - **`CollectionService._store_and_commit`'s single `IntegrityError` retry — the code that
    closes this epic's named concurrent-double-poll risk — has no test.** Round 3 verified it
    correct by direct reproduction and declined to block. Coverage was commissioned and the
    run was stopped before it landed, so this ships as a known hole and is the first thing
    E03-S02 should close, given it is the story where surge cadence makes overlap routine.
  - Only X has adapters, so a cycle polls one platform. The other three are configured and
    refuse loudly rather than collecting nothing.
  - The worker is a CLI (`make collect`), not a supervised service. Nothing restarts it.
  - `is_awaiting_first_results` cannot distinguish "announced before anyone is talking" from
    "querying the wrong thing". Collection health is E03-S05.
  - The Title Dashboard the story names is E05 and does not exist; the collection line lives
    on the titles list, which is the screen a studio is actually on after setup. Its mention
    count is labelled unsegmented because account typing is E04-S03.

- **E03-S02** — done · `14c15b0` · 8 tests · 470 backend tests · `make check` + `npm run check` +
  build green. Two review rounds.

  What landed: `CadencePhase` and `phase_for_day` in `app/core/cadence_phase.py`, replacing
  S01's single rate with dormant 2/day, campaign 12/day and release surge 48/day. **The
  windows are derived, not chosen.** The concept note fixes the three rates and the ~$273
  total but never says how long each phase lasts; working backwards over its six-month
  campaign gives surge at release −2…+4 and campaign at −30…+28, which is 124 dormant + 52
  campaign + 7 surge days = 1,208 polls × $0.225 = **$271.80**. `cadence_cost.py` computes
  exactly that by walking the same `phase_for_day` the scheduler polls by, so a window moved
  here moves the number E09-S04 reads in the same commit rather than silently invalidating
  the epic's gate. A test asserts the figure and says in its failure message to update the
  concept note rather than the assertion.

  **Escalation had to be able to outrun the rate it was escalating away from.** A cadence
  decision made when a cycle was queued is only revisited when that cycle *finishes*, so a
  dormant title at 2/day would take twelve hours to act on a controversy — most of a news
  cycle. `reconcile_pending_cadence` re-asks the policy about cycles that are already queued,
  from the worker tick, bounding the reaction at one tick instead. It recovers each run's
  anchor as `scheduled_for` minus the interval implied by its *stamped* rate, which is
  precisely the arithmetic that produced `scheduled_for`, so reconciling ten times running
  gives the same answer as reconciling once — `now + interval` would push the cycle a tick
  further out on every pass. It is **one-directional**: de-escalation waits for the next
  successor, costing at most one poll at the old rate, because a policy that oscillated could
  otherwise keep pushing a due cycle away from itself and a title that never polls is far
  worse than one that polls once too often.

  The phase is stamped on `collection_runs` as history but the dashboard reads it **live**.
  Reading the stamp is the obvious choice and it is wrong here: it would show a studio "quiet
  period" for up to a full interval after their title started surging, which is the exact lag
  the story exists to remove. The cost is that `next_run_at` can trail the rate beside it by
  one worker tick; showing the change late is the worse of the two.

  **The one-step escalation rule was documented and not implemented — round 1 caught it.**
  `PhaseCadencePolicy` claimed "the worst a volume heuristic can do to a bill is move a title
  from 2/day to 12/day; surge rates stay the calendar's to grant", but the guard only skipped
  titles *already* at surge, so a campaign title with a spike went straight to 48/day. That is
  not a corner: campaign is the widest window this product has, and a trailer drop or song
  release routinely clears a 3× baseline, so titles would have sat at release-week rates for
  weeks against a model that budgets surge for seven days. The ceiling is now a named constant
  (`HIGHEST_VOLUME_ESCALATED_PHASE`) that `is_volume_escalatable` derives from, so the rule and
  the docstring asserting it are one fact rather than two that drifted. Round 2 verified the
  fix by reintroducing the old guard and watching the new regression test fail.

  **The epic's outstanding test hole from E03-S01 is closed.**
  `CollectionService._store_and_commit`'s single `IntegrityError` retry — the code that closes
  the concurrent-double-poll risk — shipped untested and was recorded as this story's to cover.
  It now has one, built over a file-backed database with two independent sessions and a rival
  insert landing between `_store`'s read of known ids and its commit. Confirmed sensitive by
  both the tester and the reviewer independently: with the retry removed the whole page is
  rejected, including the post nobody collided on.

  Known limits, recorded rather than hidden:
  - Volume escalation is deliberately **not** modelled in the cost projection. It responds to
    something unplanned, and a projection budgeting for the average controversy would be a
    projection of a title that does not exist. It surfaces as an overrun instead, which is
    what E09 needs to alert on.
  - Reconciliation scans queued runs furthest-due-first, capped at
    `COLLECTION_CADENCE_RECONCILE_BATCH_SIZE` (50). Runs due soonest are excluded on purpose —
    they re-derive their cadence by executing — but a deployment with far more than 50 active
    titles on slow cadences would reconcile them across several ticks rather than one.
  - The escalation heuristic compares a title only against its own past, so it cannot
    distinguish a genuine controversy from a bot burst. It is capped at campaign rates for
    that reason, and every escalation logs at `warning` so an unexpected bill has a line to
    find.
  - `COLLECTION_ADAPTIVE_CADENCE=false` restores S01's flat policy. That is the escape hatch
    for a deployment where adaptive cadence is the code path suspected of costing money.
  - Per-platform cadences, customer-editable cadence and staleness detection are all out of
    scope and none were built.

- **E03-S03** — done · `3e47d7a` · 11 tests · 481 backend tests · `make check` + `npm run check` +
  build green. **One review round, passed.**

  What landed: a `CollectionWindow` on the collection port — two instants, and deliberately
  not an operator — with each X adapter translating it into its own vendor syntax:
  `since:`/`until:` *inside* tikhub's keyword string, `start`/`end` as body fields for apify.
  That asymmetry is the whole argument for the window living at the port rather than being
  built by the caller, and it is the S07 rule holding under the first feature that needed
  dates. Alongside it `collection_backfills`, a request and its receipt; a page-capped walk;
  and `mentions.is_backfilled`.

  **The date range is a request parameter, not a filter, and that is the cost decision.**
  Paging back through the present until the dates matched would mean paying for every page
  between now and a trailer launch six weeks ago. Asking the provider for the range costs
  the pages in the range.

  **A separate table rather than another trigger on `collection_runs`.**
  `uq_collection_run_one_pending_per_title` allows a title exactly one pending cycle, so a
  backfill living in that table would mean asking for history stopped live collection — or
  that the constraint keeping a title from being double-polled had to be weakened to permit
  it. `collection_backfills` carries its own partial unique index for its own reason: this is
  the only control in the product that spends a lump of money on a button press, and a
  double-click on a slow connection is the ordinary way to press it twice, where the failure
  is not a duplicate row but a duplicate invoice. The reviewer confirmed by mutation that the
  index, not the service-side check, is what actually refuses the second one.

  **The estimate is a ceiling and says so.** `backfill_cost.py` quotes variants x platforms x
  page cap, priced off the endpoint catalogue, so PER_CALL depth and PER_RESULT volume are
  charged by the two different formulas the catalogue already distinguishes (§7 rules 2 and
  3). A platform with no usable route is quoted as *unavailable* rather than at $0.00 — a
  zero line beside Instagram reads as "free", which is the opposite of "will not run". The
  walk then stops on whichever of three conditions comes first: range covered, provider out
  of pages, page cap. `is_depth_limited` and `has_reached_page_cap` separate "the platform
  stopped serving history" from "our own cap stopped us", because only one of those is
  something an operator can change.

  **Found by a manual end-to-end run before any test existed:** comparing the depth reached
  against the requested range raised `TypeError` mid-walk, after a page had already been paid
  for. SQLite returns stored datetimes naive while adapters produce aware ones — the same
  class of defect the E03-S04 entry above records, and the reason `app/core/timestamps.py`
  exists. Fixed at the boundary rather than at the comparison: `CollectionWindow` normalises
  both bounds on construction, so every site comparing against a window is correct by
  construction instead of by memory. The tester and the reviewer independently confirmed the
  guard is sensitive by removing it and watching the specific test fail.

  **An E03-S07 contract test changed its expectation, deliberately.**
  `test_collection_source_port_speaks_platform_query_page_and_limit_only` asserted the port's
  exact parameter list; it now includes `window`. The rule that test defends is that nothing
  above the port names a vendor, and two datetimes do not — the operators stay in the
  adapters. Recorded in the test itself rather than edited silently, and explicitly accepted
  by the reviewer.

  `attribution.py` was extracted from `CollectionRunService` so a backfilled post credits the
  query variant that found it. Without it, a regional alias that worked throughout the weeks
  before signup would read to alias discovery (E02-S04) as an alias that found nothing — the
  opposite of what a backfill is for.

  Known limits, recorded rather than hidden:
  - **Completeness is impossible to promise and is not promised.** Platform search depth is
    the platform's to decide; the UI states the depth reached, in the same place it states
    the cost, and calls a short stretch a sample rather than the record.
  - A slow backfill delays *that worker's next tick* of scheduled cycles by its own duration.
    Mitigated by a batch size of 1 and by backfills running after cycles, never before.
  - The Title Dashboard the story names is E05 and does not exist; the action lives on the
    titles list beside the collection line E03-S01 put there, and is owner-only.
  - The last selectable day is yesterday. Today is still being collected live, so backfilling
    it would pay a premium for what the scheduled poll brings in for nothing — and would mark
    posts as historical that are not.
  - `charged_cost_usd` is derived from the catalogue's list prices, not from a provider
    invoice. Reconciling the two is E09's.

- **E03-S05** — done · `9007554` · 18 tests · 499 backend tests · `make check` + `npm run check` +
  build green. **Three review rounds**, each one finding a defect in the alerting path and no
  other.

  What landed: `collection_platform_results`, one row per platform per cycle. Until this table a
  cycle recorded a single outcome for all four platforms at once, which answers "is this title
  collecting" and cannot answer the question the story asks — a cycle where three platforms
  worked and one did not is a success by every counter on `collection_runs`, and that is the
  exact shape of the failure the story is about. A log rather than a current-state row per
  platform, because *repeated* failure is the alerting signal the Notes ask for and telling a
  blip from an outage needs the history. Beside it `app/core/collection_health.py` holds the
  staleness arithmetic as pure functions, on the same reasoning as `cadence_cost`: the rule the
  dashboard renders, the interval alerting counts against, and the tests all read one fact.

  **Staleness is relative to the title's current cadence phase, and that is what makes it mean
  anything.** Eight hours of silence on a dormant title polled twice a day is a title behaving
  normally; the same eight hours in release surge is an outage that has run most of an opening
  weekend. One absolute threshold would either scream through every quiet campaign or stay
  silent through exactly the window the story is written about. The tolerance is **two**
  intervals, not one: after one interval a poll is merely *due*, and a worker tick landing late
  is not a coverage gap. Anything tighter turns the indicator into a flapping light people learn
  to ignore, which is worse than no light, because this one only works if being lit is believed.

  **`data_as_of` is the oldest success among the *reporting* platforms**, and each half is
  load-bearing. Oldest rather than newest, because an "as of" is a claim about everything on the
  screen and quoting the most recent success lets one platform that polled a minute ago speak
  for three that did not. Reporting-only because the story says so — but that is only honest if
  the excluded platforms are named where their data appears, which is why `StalePlatformWarning`
  is exported separately from `PlatformCoverage`: a warning each chart writes for itself is a
  warning some chart will forget. E05's charts mount it and declare which platforms they cover.

  **"Never succeeded" splits on whether anything was ever tried**, which is the whole difference
  between a new title and a broken one. Never attempted is `pending` — greeting every freshly
  created title with a warning is the fastest way to teach people to ignore it. Attempted and
  never once successful is `stale` immediately, without waiting an interval, because that is
  what a misconfigured platform looks like and silence is the wrong first thing to say about it.

  **All three review rounds landed on the same forty lines, and the third fix was needed because
  of the second.** Round 1: the alert fired on *every* cycle past the threshold, so at surge
  cadence a known outage would page data ops 48 times a day — the fatigue the alerter's own
  docstring argues against. Fixed by comparing the count to the threshold for **equality**, so a
  platform alerts on the crossing and then goes quiet while it stays broken. Round 2 found that
  fix correct and found what it had made dangerous: the `try/except` guarding the alerter wrapped
  the *whole* loop, so if one platform's alerter raised, every later platform that crossed on the
  same cycle was skipped — and under equality gating a skipped crossing is never retried, so the
  alert is **lost rather than delayed**, on precisely the shared-upstream outage that most needs
  paging. Under the old `>=` behaviour the same skip was harmless. The reviewer reproduced it with
  four platforms failing together and an alerter raising on one. Isolation is now per iteration.
  Round 2 also flagged, non-blocking, that `window < threshold` caps the count below a threshold
  it can never equal — alerting silently switches itself off while every dashboard keeps reporting
  staleness correctly, which is the worst shape this bug could take: fully instrumented, pages
  nobody. Refused at startup now, with `0` kept as the deliberate way to turn alerting off.
  Round 1 also found `status_for_title` deciding cadence twice per title — `PhaseCadencePolicy.decide`
  issues a volume query on dormant titles, so a list rendering one status per row doubled it.
  The decision is handed to `CollectionHealthService` instead, which also guarantees the rate a
  studio is shown and the interval their staleness was judged against are one decision.
  Round 3 passed, verifying both fixes by reintroducing each bug and watching the specific test
  fail. Migration/model agreement confirmed with `alembic check` after running all eleven
  migrations from base into a scratch Postgres ("No new upgrade operations detected").

  Known limits, recorded rather than hidden:
  - The stale warning is greyscale with an icon and an explicit sentence, not red. This is the
    case where invariant D costs something and is still right: a stale platform is the most
    alarming thing on the screen, but sentiment owns saturated colour and a red meaning "broken"
    would compete with the red meaning "negative" on the same screen.
  - `recent_for_platform` is one query per **non-reporting** platform rather than one batched
    read. Bounded by the platform count and free on the healthy path. Batching means a
    top-N-per-group query that neither Postgres nor SQLite express portably, and the
    fetch-a-slice-and-group-in-Python version can drop a quiet platform's rows when a noisy one
    dominates the slice — a coverage screen that under-reports a gap is the one bug this story
    cannot ship.
  - Alerting reaches data ops as a structured `error` log line. `CollectionHealthAlerter` is the
    seam; something that actually pages is **E08's**, and until it is bound nobody is woken up.
  - `recent_for_platform` breaks ties on a random UUID, so two attempts for the same title and
    platform sharing a `finished_at` to the microsecond would order arbitrarily. Not reachable —
    one title's cycles are serialised by `uq_collection_run_one_pending_per_title`.
  - Only X has adapters, so three of the four configured platforms report `pending` until they
    are first attempted and `stale` from their first attempt onward. That is the intended
    reading: they are configured and not collecting.
  - The screen is still the titles list, not the Title Dashboard the story names. That dashboard
    is E05.
