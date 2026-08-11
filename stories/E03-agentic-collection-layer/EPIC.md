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

| ID | Summary | Phase |
|---|---|---|
| E03-S01 | Start collecting automatically the moment a title is created | 1 |
| E03-S02 | Shift polling cadence with the campaign phase | 1 |
| E03-S03 | Backfill the conversation from before I signed up | 1 |
| E03-S04 | Store raw payloads verbatim and reprocess without re-paying | 1 |
| E03-S05 | See per-platform collection health and coverage gaps | 1 |
| E03-S06 | Deduplicate reposts and cross-platform repeats | 1 |
| E03-S07 | Keep the collection agent's tool interface provider-agnostic | 1 |

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
