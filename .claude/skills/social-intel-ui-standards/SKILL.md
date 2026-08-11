---
name: social-intel-ui-standards
description: Use this skill whenever building, designing, reviewing, or modifying ANY user-facing screen, component, chart, or layout for the Agentic Social Media Control Centre — the entertainment-industry social media intelligence platform. Covers the Overview Dashboard, Mentions Feed, Reply Approval Queue, Trend Detection View, Influencer Discovery, and any new screen or widget added to them. Trigger even when the request sounds like plain frontend work and never mentions design systems — "build the mentions list", "add a sentiment chart", "make this page look modern", "wire up the approval screen", "show top influencers", "add a filter" all qualify. Do NOT build the screen AS-IS from the raw request. This platform has four global invariants — account-type segmentation, language provenance, human approval gates, and sentiment colour budget — that are invisible in a feature request but expensive to retrofit. Check them first, then build.
---

# Social Intelligence Platform — UI Standards

A pre-build checkpoint for the Agentic Social Media Control Centre frontend. The behaviour this enforces: **before writing a component, work out which of the four invariants the screen touches, satisfy them in the design, then build.**

This is not a general design-system skill. It encodes decisions specific to a social-listening product for film and music campaigns, where the data is multilingual, partly non-organic, and drives actions that get posted publicly under a client's name.

## Why this exists

Each invariant below is cheap at design time and expensive later, because each one changes what a number *means* rather than how it looks:

- A sentiment percentage computed over trade accounts and distributor posts is a measure of campaign activity, not public opinion — but it renders identically to the real thing.
- Platform language labels are wrong roughly half the time on Tamil and Telugu content, so a language filter built on the raw field silently drops content and nobody notices.
- An approve button with no friction turns a governance principle into an honour system.
- Once accent colours, gradients, and status chips are all saturated, red no longer reads as negative sentiment — it reads as decoration.

Retrofitting any of these means re-auditing every screen that displays an aggregate. Getting them into the first component is nearly free.

## Workflow

Run this for every UI request against this platform, including small ones. If a request genuinely touches none of the invariants — a spacing fix, a typo, a build config change — say so in one line and skip ahead to building.

### Step 1 — Classify the screen

Ask of the request, not of the user:

1. **Does it display an aggregate?** Any count, percentage, average, rate, ranking, or chart computed over more than one mention → **Invariant A (account-type segmentation)**.
2. **Does it display or filter mention text?** Any feed, card, quote, sample, search, or language control → **Invariant B (language provenance)**.
3. **Does it produce an outbound action?** Anything that posts, replies, DMs, schedules, or bulk-approves → **Invariant C (human approval gate)**.
4. **Does it use colour to encode anything?** Charts, badges, status, highlights, heat → **Invariant D (colour budget)**.
5. **Does it show polled data?** Anything fed by the collection layer → **freshness state** (see `references/states-and-data-realities.md`).

Most screens hit three or four. Check all, don't stop at the first.

### Step 2 — Apply the invariants

Read the detail in `references/invariants.md` — it has the concrete component patterns for each. The short form:

**A. Account-type segmentation is global chrome, not a per-screen filter.**
The organic / trade / owned-media / promotional selector lives in the app shell, persists across navigation, and is visible on every screen that shows a number. Every aggregate carries a segment label in its subtitle or tooltip. Default to organic-only, because that is the number people think they are reading. A filter buried inside the Mentions Feed will be missed by someone reading an Overview sentiment figure.

**B. Language needs provenance, not just a value.**
Distinguish platform-reported language from the pipeline's own detection, and surface detection confidence. Low-confidence and code-mixed items get a visible marker. Language filters query the detected field, never the raw platform field. Never hide a mention because a platform label disagreed with detection — flag it instead.

**C. Approval friction scales with irreversibility.**
No path exists from AI-generated text to a live post without an explicit human action on that specific text. Bulk approve, if it ships at all, requires a scrollable preview of every message in the batch and a typed or held confirmation. Show the source mention beside every draft reply — approving a reply without its context is approving blind. Log who approved what.

**D. Sentiment owns saturated colour; everything else is neutral.**
One diverging scale for sentiment and nothing else competing with it. Chrome, surfaces, borders, and non-sentiment status are greyscale with at most one restrained brand accent. Never encode sentiment by colour alone — pair with label, icon, or position for accessibility and for greyscale exports.

### Step 3 — Build

Stack and conventions are in `references/stack-and-patterns.md`. Defaults: React + TypeScript, Tailwind, shadcn/ui, Recharts, TanStack Query for server state. Build against real payloads from the collection spike, not lorem ipsum — Tamil script, code-mixed Latin-script strings, emoji-heavy text, 30-character handles, and missing avatars will break naive layouts, and finding that in week one is much cheaper than after a design review.

Read `references/states-and-data-realities.md` before building any list, card, or chart. It covers the loading / empty / error / stale / partial states this product actually needs, and the specific content shapes that break layouts here.

### Step 4 — Resolve "make it sleek"

Requests for a sleek, smooth, modern interface are common and worth interpreting rather than executing literally. In a monitoring tool where colour carries meaning, the marketing-site version of sleek actively harms legibility.

Translate it as: **restraint and performance, not decoration.**

- Sleek → tight type scale, generous data density, neutral surfaces, no gradient or glass competing with sentiment colour.
- Smooth → sub-100ms interactions, no layout shift, skeletons that match final geometry, transitions only to show state change.
- Modern → keyboard navigation, real empty states, responsive tables that degrade to cards, dark mode that keeps the sentiment scale legible.

The reference point is a trading terminal or an observability console, not a landing page. If a request asks for something that would dilute the sentiment scale — a colourful accent palette, coloured category chips, a gradient hero — say so briefly, propose the neutral version, and build that. Don't refuse the aesthetic goal; redirect it to the thing that actually reads as high quality in this product.

### Step 5 — Sequence, when asked what to build first

Recommend the Mentions Feed before the Overview Dashboard, even though Overview is listed first in the brief. The feed is where language identification, account typing, and alias matching are visibly right or wrong. The dashboard aggregates data that hasn't been validated yet — it will look convincing before it is correct, which is the worst possible state for a stakeholder demo.

Suggested order: **Mentions Feed → Reply Approval Queue → Overview Dashboard → Trend Detection → Influencer Discovery.**

If the user has a reason to go dashboard-first, build it — but wire the segment selector and a visible freshness indicator in from the start, and label sample numbers as unvalidated.

## Escalate rather than deciding

Raise these to the user instead of picking silently:

- **Auto-posting or scheduled replies without per-item approval.** This contradicts the platform's governance principle. Name the conflict and get an explicit decision.
- **Showing AI sentiment as a bare number when the agreement rate against human-labelled code-mixed content is unknown or below the project's gate.** Propose a confidence indicator or a "provisional" label instead of silently presenting it as ground truth.
- **Displaying an artist's personal perception dashboard to a non-artist persona** (production house or agency workspace). Persona-scoped visibility of individual perception data is a product and privacy decision, not a frontend one.
- **Any aggregate that cannot be attributed to a segment** because the account-type classification is missing for that source. Show it as unsegmented and flagged, don't fold it silently into the organic number.

## Reference files

- `references/invariants.md` — the four invariants in full, with component patterns and worked examples of the right and wrong version of each.
- `references/stack-and-patterns.md` — stack choices, component conventions, chart rules, performance targets, accessibility.
- `references/states-and-data-realities.md` — required UI states for polled data, and the content shapes (script, length, code-mixing, missing fields) that break layouts in this product.
