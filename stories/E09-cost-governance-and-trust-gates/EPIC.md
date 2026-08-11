# Epic E09 — Cost Governance & Trust Gates

**Phase:** 1
**Source:** Concept note §7 (unit economics + cost-control rules), §9 (gates and the fail-safe), §8

## Epic hypothesis

**We believe that** enforcing cost controls in code and measuring the accuracy gates before we ship a
number
**will result in** a product whose unit economics are known per title and whose published numbers are
defensible,
**We will know we are right when** measured cost per title tracks the §7 model, and every number on
screen either clears its gate or is not shown.

## Why this epic exists

Two open risks from the concept note live here, and both can kill the product rather than degrade it.

**Cost.** Collection is cheap and predictable (~$0.225/poll, ~$273/title). Analysis is not: 500K–2M
mentions cost ~**$90** on a small model and ~**$900** on a frontier model, and a single title can
approach **$1,200** all-in if code-mixed content forces us up the model ladder. A flat per-title price
therefore does not work — a tentpole is 10–20× a mid-budget film. The recommended shape is a **base
tier plus a metered volume component**, banded by expected scale.

**Trust.** The concept note's most consequential product decision:

> **If the sentiment gate fails:** ship without a sentiment number. Launch on volume, themes,
> account-type split, and spikes. Putting an inaccurate sentiment score in front of a production house
> destroys trust permanently and is not recoverable.

That decision needs to exist as a working switch in the product, not as a paragraph in a document.

## Personas served

- **Internal Data Ops / Finance** — cost controls and unit economics.
- **P1 / P2 / P3** — as beneficiaries of numbers that are gated before they are shown.

## Stories

| ID | Summary | Phase |
|---|---|---|
| E09-S01 | Confirm an endpoint's price model before every paid run | 1 |
| E09-S02 | Cap every PER_RESULT call so no run can run away | 1 |
| E09-S03 | Stop spend server-side with workspace controls | 1 |
| E09-S04 | See actual cost per title against its projection | 1 |
| E09-S05 | Price by tier plus metered volume | 1 |
| E09-S06 | Measure the accuracy gates against human labels | 1 |
| E09-S07 | Suppress sentiment everywhere when its gate is not cleared | 1 |

## The gates (concept note §9)

| Gate | Threshold | Status |
|---|---|---|
| Collection cost per title per day | Within §7 model | To measure |
| Sentiment agreement vs human labels (code-mixed reported separately) | ≥ 0.75 | To measure — decides both the feature and the pricing model |
| Entity-match precision on anchored query | ≥ 0.85 | Provisionally met at 1.00 |
| Account-type classification accuracy | ≥ 0.85 | To measure |

## Cost-control rules adopted as engineering constraints (§7)

1. `monid_inspect` before every `monid_run` — confirm the price model.
2. Prefer **PER_CALL** endpoints; on PER_CALL, cost is driven by pagination depth, not result count.
3. **Never** call a PER_RESULT endpoint without a hard result cap.
4. Set **workspace spend controls** in Monid as a server-side stop; blocked runs return `BLOCKED`
   with a reason.

## Dependencies

- **Blocked by:** E03 (the layer being governed), E04 (the models being measured).
- **Blocks:** the Phase 2 decision — these are the gates Phase 2 is conditional on.

## Out of scope

- The legal review of scraping-sourced data for commercial analytics in India (§11.4) — tracked as
  the top open risk, but it is a workstream, not a story.
