# Epic E08 — Alerts & Digests

**Phase:** 1 (daily digest), 3 (spike/sentiment alerts, agency digests)
**Source:** Concept note §5.5, §9 (MVP includes daily email digest), §10 (north star)

## Epic hypothesis

**We believe that** pushing a daily digest and event-triggered alerts to owners
**will result in** owners returning to the dashboard weekly rather than at the moment of crisis,
**We will know we are right when** weekly active entities with an owner who viewed them rises, and
digest-to-dashboard click-through is a meaningful share of weekly sessions.

## Why this epic exists

The north-star metric is *weekly active entities with an owner who viewed the dashboard that week*.
A dashboard nobody opens scores zero on it. The digest is the mechanism that makes the product part
of a marketing head's morning rather than something they remember during a crisis.

The daily email digest is in the **Phase 1 MVP scope** explicitly. Spike and sentiment-shift alerts
follow in Phase 3 alongside the agency workspace.

One constraint governs the whole epic: **an alert built on an unvalidated sentiment number is worse
than no alert.** If the §9 sentiment gate is not cleared, sentiment-shift alerts do not ship — the
same rule as E09-S07.

## Personas served

- **P1 Production House** — daily digest, spike alerts.
- **P2 Artist** — digest scoped to their own perception.
- **P3 Agency** — cross-client digest.

## Stories

| ID | Summary | Phase |
|---|---|---|
| E08-S01 | Receive a daily digest for my title | 1 |
| E08-S02 | Be alerted when conversation spikes | 3 |
| E08-S03 | Be alerted when organic sentiment shifts materially | 3 |
| E08-S04 | Tune alert thresholds so I'm not trained to ignore them | 3 |
| E08-S05 | Receive one cross-client digest as an agency | 3 |

## Dependencies

- **Blocked by:** E04-S05 (spike detection), E05 (the destination of every link).
- **Gated by:** E09-S07 for anything containing a sentiment number.

## Out of scope

- SMS, WhatsApp, and Slack delivery channels (email only in v1).
- Predictive alerts.
