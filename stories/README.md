# Product Backlog — Agentic Social Media Control Centre

Derived from `concept-note-v0.2-social-intelligence-control-centre.md` (11 August 2026).

Format: Mike Cohn user stories with Gherkin acceptance criteria, per the `user-story` skill.
One story per file, one folder per epic.

## Epics

| Epic | Folder | Stories | Phase |
|---|---|---|---|
| E01 — Organizations, Access & Membership | `E01-organizations-access-membership/` | 6 | 1–3 |
| E02 — Title Setup & Identity Discovery | `E02-title-setup-identity-discovery/` | 5 | 1 |
| E03 — Agentic Collection Layer | `E03-agentic-collection-layer/` | 7 | 1 |
| E04 — AI Analysis Pipeline | `E04-ai-analysis-pipeline/` | 7 | 1 |
| E05 — Title Dashboard | `E05-title-dashboard/` | 9 | 1 |
| E06 — Artist Entities & Artist Dashboard | `E06-artist-entities-and-dashboard/` | 5 | 2 |
| E07 — Agency Workspace & Multi-Client Reporting | `E07-agency-workspace-multi-client/` | 4 | 3 |
| E08 — Alerts & Digests | `E08-alerts-and-digests/` | 5 | 1, 3 |
| E09 — Cost Governance & Trust Gates | `E09-cost-governance-and-trust-gates/` | 7 | 1 |

**55 stories.** Each epic folder has an `EPIC.md` with its hypothesis, dependencies, and story list.

## Phase 1 (MVP) scope

> One production house tracks one title through a real campaign window and finds the dashboard
> credible enough to act on.

Everything in **E02, E03, E04, E05, E09**, plus **E01-S01/S02** (org + viewers) and **E08-S01**
(daily digest). Tamil-market focus; X, Reddit, YouTube, with Instagram conditional.

Deferred: **E06** (Phase 2), **E07** and the rest of **E08** (Phase 3).

## Suggested build order

1. **E01-S01, E01-S02** — an org to hang everything off.
2. **E02-S01, E02-S02** — a title with a rich identity set and a release anchor.
3. **E03-S01, S04, S07** — collection running, payloads stored, provider abstracted. E03-S04 first
   among these; without the raw store, every later pipeline change costs real money.
4. **E09-S01, S02, S03** — cost controls, before cadence scales up in E03-S02.
5. **E04-S01 → S03** — language ID and account-type classification. These two carry the product's
   differentiation and both gates.
6. **E05-S01 → S03, S05, S08** — the dashboard skeleton with organic-only default, the persistent
   account-type filter, and coverage disclosure.
7. **E09-S06, E09-S07** — measure the gates, then wire the suppression switch *before* the first
   customer sees a sentiment number.
8. Remainder of E02/E03/E04/E05, then E08-S01.

## The three things the live data changed

Every story traces back to the concept note. Three findings shape the whole backlog:

1. **Language ID is mandatory** (§6.2). Platform language tags were wrong for roughly half the
   non-English sample — Telugu tagged `en`, Tamil tagged `in`, `ht`, and `fi`. → **E04-S01**.
2. **Account type is a first-class dimension** (§6.3). The corpus mixes organic audience, trade
   trackers, owned media, and promotional accounts; averaging across them measures campaign activity,
   not public opinion. → **E04-S03, E05-S02, E05-S03**.
3. **Aliases must be discovered, not declared** (§6.1). Twenty posts produced seven organic hashtags
   and multiple name misspellings. → **E02-S04**.

## Gates before Phase 2

| Gate | Threshold | Story |
|---|---|---|
| Collection cost per title per day | Within §7 model | E09-S04 |
| Sentiment agreement vs human labels (code-mixed separate) | ≥ 0.75 | E09-S06 |
| Entity-match precision on anchored query | ≥ 0.85 (provisionally 1.00) | E09-S06 |
| Account-type classification accuracy | ≥ 0.85 | E09-S06 |

**If the sentiment gate fails, ship without a sentiment number** — E09-S07 makes that switch real.

## Out of scope for v1 (all epics)

Posting or replying on any platform · ad management · influencer outreach execution · box-office data
integration · paid campaign analytics · multimodal (video/image) analysis.

## Open items not covered by stories

- **Legal read** on scraping-sourced data for commercial analytics in India (§11.4) — the top open
  risk and a blocker on commercial launch, but a workstream rather than a story.
- **Monid open questions** (§11.6): rate limits per key at surge cadence, server-side result caps on
  PER_RESULT endpoints, provider substitution behaviour on outage. These constrain E03-S07,
  E09-S02, and E09-S03.
- **T1–T7 spike battery** (§11.1) — the outstanding T1a bare-`DC` baseline quantifies the
  entity-resolution gap that justifies E02-S01's rich setup flow.
