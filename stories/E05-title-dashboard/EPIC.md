# Epic E05 — Title Dashboard

**Phase:** 1
**Source:** Concept note §5.4, §9 (MVP definition), §11.5 (revised UI brief), §10

## Epic hypothesis

**We believe that** a Title Dashboard defaulting to organic-only sentiment, with account type as a
persistent filter and coverage gaps stated on the page
**will result in** a production house finding the numbers credible enough to act on during a real
campaign,
**We will know we are right when** at least one pilot production house uses the dashboard in a real
campaign decision, and weekly active entities with an owner who viewed them is non-zero and growing.

## Why this epic exists

This is the MVP's whole customer-facing surface: *one production house tracks one title through a
real campaign window and finds the dashboard credible enough to act on.*

Two design commitments carry the concept note's central insight onto the screen:

1. **Organic-only by default.** A sentiment number averaged across trade, owned, and promotional
   accounts tells a studio what its own campaign is doing. The default view must exclude that.
2. **Account type as a persistent control**, not a buried filter — it appears on Overview and the
   Mentions Feed and stays applied as the user moves between them.

The dashboard must also survive the worst case: if the sentiment gate fails, §9 says ship **without
a sentiment number** — on volume, themes, account-type split, and spikes. Every story here is
written so removing sentiment leaves a coherent product.

## Personas served

- **P1 Production House** — the primary and, in Phase 1, only viewer.

## Stories

| ID | Summary | Phase |
|---|---|---|
| E05-S01 | Read volume as a trend split at the release date | 1 |
| E05-S02 | Read sentiment that defaults to organic audience only | 1 |
| E05-S03 | Filter the whole dashboard by account type, persistently | 1 |
| E05-S04 | Compare how each platform is behaving | 1 |
| E05-S05 | Drill into the mentions feed and open the source post | 1 |
| E05-S06 | See the posts actually driving the conversation | 1 |
| E05-S07 | Explore themes and their movement over time | 1 |
| E05-S08 | See stated coverage gaps instead of a falsely complete number | 1 |
| E05-S09 | Export the current view as a shareable report | 1 |

## Dependencies

- **Blocked by:** E02 (release date anchor), E03, E04.
- **Blocks:** E06 and E07 reuse these components.

## Out of scope

- Reply approval queues or any posting/engagement action (removed from the UI brief in §11.5;
  explicitly out of scope for v1 in §5).
- Comparable-title benchmarking and pre-release buzz index (Phase 4).
- Box-office data overlays (out of scope for v1).
