# Concept Note v0.2 — Agentic Social Media Control Centre for Entertainment

**Supersedes:** v0.1 (pivot draft)
**Date:** 11 August 2026
**Author:** Vicky (Product)
**Status:** For internal review — collection layer validated against live data

---

## What changed since v0.1

v0.1 was written before any live data. We have since connected Monid via MCP, explored the catalog, and executed real paid calls against a live release (*DC*, Sun Pictures, 7 Aug 2026). Three things changed materially:

1. **The pivot is validated.** Both blockers that killed the original architecture are gone, at confirmed prices.
2. **The pipeline needs two stages that weren't in v0.1** — language identification and account-type classification. Both were discovered from real data, not theory.
3. **The cost model moved.** Collection is cheap and predictable. AI analysis is the real budget risk, and it is coupled to the code-mixed language problem.

---

## 1. One-line pitch

A control centre where production houses, artists, and talent agencies see — in one place — how their movie, web series, or indie music release is performing across social media, before and after release, powered by an agentic data-collection layer (Monid) instead of hand-built platform connectors.

## 2. The pivot, now evidenced

v0.1 argued the pivot on two blockers. Both are resolved, with prices confirmed via `monid_inspect`:

| Original blocker | Resolution | Price |
|---|---|---|
| X API cost-gated behind subscriptions | `tikhub /api/v1/twitter/web/fetch_search_timeline` — keyword search, no subscription | $0.0015 **PER_CALL** |
| Meta Graph API has no public keyword search | `tikhub /api/v1/instagram/v2/search_hashtags`, `/v2/general_search` | $0.003 **PER_CALL** |

Plus Reddit (`tikhub` dynamic search, $0.0015 PER_CALL) and YouTube comments (`tikhub`, $0.0015 PER_CALL; `apify` scraper, $0.00225 PER_RESULT).

**Live execution confirmed.** A run against `"Lokesh Kanagaraj DC"` returned 20 posts in 3.9 seconds for $0.0015, with a working pagination cursor. Full metadata: author, follower count, timestamp, engagement counts, hashtag entities, media objects.

Access is no longer the question. **Quality and unit cost are.**

## 3. Problem statement

Unchanged from v0.1. Entertainment releases live or die on social conversation, and the people who need to read it are least equipped to:

- **Production houses** get fragmented, delayed, agency-filtered reports.
- **Actors and artists** have no independent view of their own public perception.
- **Agencies** juggle multiple celebrity clients with spreadsheet-and-screenshot reporting.

Incumbents (Brandwatch, Sprinklr, Meltwater) are priced for global enterprise brands, are weak on Indian regional-language content, and have no concept of a *title* as the unit of tracking.

**The live data sharpened one part of this.** Existing tools would report *DC* as broadly positive. But a large share of that volume comes from box-office tracker accounts, distributors, and cinema chains posting their own promotions. A "positive sentiment" number built on that is a production house reading its own press back to itself. **Measuring genuine audience opinion requires separating it from trade and marketing chatter — and nobody in this market does that.** See §6.

## 4. Personas

Unchanged in structure from v0.1.

### P1 — Production House
Creates and owns titles: name and aliases, poster/thumbnail/cover assets, cast and crew, official hashtags, key campaign dates. Sees the Title Dashboard. Invites tagged artists and agencies.

### P2 — Actor / Artist
Personal perception dashboard — volume, sentiment, themes, notable posts. Sees tagged titles read-only, filtered to "conversation about the title that mentions me."

**Validated complication:** in the *DC* corpus, Lokesh Kanagaraj appears simultaneously as (a) the film's lead actor, (b) a celebrated director whose brand the film is boosting, and (c) an upcoming collaborator on an unrelated Allu Arjun project (`#AA23`) that surfaces inside DC-anchored results. The Artist Dashboard's core filter is separating these three. This is a real, testable requirement, not a hypothetical.

### P3 — Social Media Management Agency
Multi-client workspace, client switching, per-client access control, exportable periodic reports.

**Access model:** Organization (production house or agency) → Entities (Title, Artist) → Memberships (owner, tagged artist, agency manager, viewer).

## 5. Core capabilities

1. **Entity setup** — Title and Artist records with rich identity. Identity richness drives collection precision (§6.1).
2. **Agentic collection** — collection agent uses Monid across X, Reddit, YouTube, Instagram on adaptive cadence. Raw payloads stored verbatim for reprocessing without re-paying.
3. **AI analysis** — language ID, account-type classification, sentiment, theme extraction, spike detection, narrative summarisation. Swappable behind an internal interface.
4. **Dashboards** — Title, Artist, Agency multi-client. Pre-release vs post-release is first-class, anchored to release date.
5. **Alerts & digests** — spike, sentiment-shift, daily/weekly digest.
6. **Access & tagging** — production house tags artists; agencies manage artist profiles.

**Out of scope (v1):** posting or replying on any platform, ad management, influencer outreach execution, box-office data integration, paid campaign analytics.

---

## 6. Pipeline — revised from live data

v0.1 assumed: `ingest → dedupe → entity match → sentiment → aggregate`.

The real corpus shows that is wrong in two places. Revised:

```
ingest → dedupe → entity match → LANGUAGE ID → ACCOUNT-TYPE CLASSIFY
       → sentiment (routed by language) → theme extraction → aggregate
```

### 6.1 Entity match — validated, and it works

The anchored query `"Lokesh Kanagaraj DC"` returned **20 of 20 relevant posts**. Rich identity works.

But the corpus also proved the identity set must be **discovered, not just declared**. Organic hashtags found in 20 posts alone:

`#DCthemovie` · `#DCMovie` · `#DCFDFS` · `#DCReview` · `#DCPublicReview` · `#DCTheBloodyValentineFromAugust7` · `#DCFromAugust7`

Plus name variants in the wild: "Kankaraj", "Anirudh Ravichandran" vs "AnirudhRavichander". And confirmed contamination even inside an anchored query — one post carried `#DC #DareDevil`, the predicted DC Comics bleed.

**Product implication:** alias discovery is a **feature**, not a setup field. Seed from what the production house enters, mine the corpus for co-occurring hashtags, surface suggestions back to them for approval. This becomes a small but genuinely differentiating loop.

### 6.2 Language identification — NEW, mandatory

v0.1 assumed we could route mentions to the right sentiment model using the platform's language tag. **We cannot.** From the live sample:

| Actual content | Platform tag |
|---|---|
| Telugu in Latin script (536K views) | `en` |
| Tamil in Latin script | `in` (Indonesian) |
| Tamil film post | `ht` (Haitian Creole) |
| Tamil FDFS review | `fi` (Finnish) |

Roughly half the non-English content was mislabelled. **A language-ID step must run before sentiment routing.** This is new scope for Phase 1 and it is not optional — without it, code-mixed content is silently routed to an English sentiment model, which is exactly the failure mode we set out to avoid.

### 6.3 Account-type classification — NEW, first-class dimension

The single most important product finding. The *DC* corpus mixes at least four distinct kinds of account:

- **Organic audience** — individual viewers posting reactions
- **Trade / tracker** — box-office trackers, industry press (KeralaBxOffce, Cinemaaforu, letscinema, taran_adarsh)
- **Owned media** — the production house and its distributors
- **Promotional** — cinema chains and booking partners posting ticket links

Averaging sentiment across all four produces a number that reflects **campaign activity, not public opinion**. Classification must be a first-class pipeline dimension, and every dashboard number must be filterable by it. The default view should be organic-only.

This is also a defensible product wedge — it's the difference between a listening tool and an intelligence tool.

### 6.4 Known limitation to state honestly

A large share of high-engagement posts are **video or image with two words of text**. Text-only sentiment will systematically miss them. v1 should count these in volume, exclude them from sentiment, and label the coverage gap in the UI rather than hiding it.

---

## 7. Unit economics — revised

### Collection: cheap and predictable

Per poll, at 5 query variants × 5 pages across four platforms:

| Platform | Calls | Unit | Cost |
|---|---|---|---|
| X | 25 | $0.0015 | $0.0375 |
| Reddit | 25 | $0.0015 | $0.0375 |
| Instagram | 25 | $0.003 | $0.075 |
| YouTube (10 videos × 5 pages) | 50 | $0.0015 | $0.075 |
| **Per poll** | | | **$0.225** |

Across a 6-month campaign with adaptive cadence — dormant (2/day), campaign (12/day), release surge (48/day) — total collection lands around **$273 per title**.

### Analysis: the actual budget risk

A major Tamil release plausibly generates 500K–2M mentions across that window. Batched at 50 mentions per call:

- Small/fast model: **~$90**
- Frontier-tier model: **~$900**

**The code-mixed problem and the budget problem are the same problem.** If off-the-shelf sentiment fails on Tamil-in-Latin-script, we get pushed up the model ladder and a single title approaches $1,200 all-in. This makes the sentiment-agreement gate (§9) a unit-economics gate, not just a quality gate.

### Pricing implication

**A flat per-title price does not work.** Mention volume for a Rajinikanth or Vijay release is plausibly 10–20× a mid-budget film, and both collection and analysis cost scale with it. A flat fee loses money on exactly the tentpole titles worth selling to, while pricing the indie-music persona out entirely.

**Recommended shape:** base tier + metered volume component, with tiers banded by expected scale. The three cadence phases give a natural structure.

### Cost-control rules (adopt as engineering constraints)

1. `monid_inspect` before every `monid_run` — confirm the price model.
2. Prefer **PER_CALL** endpoints. On PER_CALL, cost is driven by pagination depth, not result count.
3. **Never** call a PER_RESULT endpoint without a hard result cap. The Apify Reddit scraper at $0.0057/result + $0.02 flat is the runaway risk.
4. Set **workspace spend controls** in Monid as a server-side stop. Runs blocked by a control return `BLOCKED` with a reason — that's the real safety net.

---

## 8. Risks

| # | Risk | Status since v0.1 |
|---|---|---|
| 1 | **Scraping legality & platform ToS** | **Unchanged and now the top open risk.** Legal review required before commercial launch. |
| 2 | Cost per tracked entity | **Partly resolved.** Collection modelled at ~$273/title. Analysis cost remains open, pending §9 gate. |
| 3 | Entity resolution | **Substantially de-risked.** 20/20 precision on anchored query. Alias discovery now a feature. |
| 4 | Code-mixed sentiment accuracy | **Worse than scoped.** Platform language tags are unreliable, so a language-ID stage is now required. Accuracy itself still untested. |
| 5 | Monid dependency | **Unchanged.** Single aggregator for the whole collection layer. Keep the agent's tool interface abstract. |
| 6 | Latency & freshness | **Improved.** 3.9s per call observed. Surge cadence is affordable. |
| 7 | Artist identity claims | Unchanged. Invite-based linking in v1. |
| 8 | **Trade/promo contamination of sentiment** | **NEW.** Mitigated by §6.3. Without it, every sentiment number is misleading. |
| 9 | **Media-only posts** | **NEW.** Text-only sentiment misses high-engagement video posts. Disclose in UI. |

---

## 9. MVP definition (Phase 1)

**Goal:** one production house tracks one title through a real campaign window and finds the dashboard credible enough to act on.

- One org type (production house), one entity type (Title), Tamil-market focus.
- Collection on X, Reddit, YouTube (Instagram if §T6 proves post-level data).
- Raw payload store + pipeline per §6, **including language ID and account-type classification**.
- Title Dashboard: volume trend, sentiment trend (organic-only default), platform split, account-type split, top posts, spike markers against campaign dates.
- Alias discovery suggestions.
- Daily email digest.

**Gates before Phase 2:**

| Gate | Threshold |
|---|---|
| Collection cost per title per day | Within model (§7) |
| Sentiment agreement vs human labels, **code-mixed subset reported separately** | ≥ 0.75 |
| Entity-match precision on anchored query | ≥ 0.85 — *provisionally met at 1.00* |
| Account-type classification accuracy | ≥ 0.85 |

**If the sentiment gate fails:** ship without a sentiment number. Launch on volume, themes, account-type split, and spikes. Putting an inaccurate sentiment score in front of a production house destroys trust permanently and is not recoverable.

**Phase 2:** Artist entities + tagging + Artist Dashboard (with the three-way Lokesh-style disambiguation filter).
**Phase 3:** Agency workspace + multi-client reporting + alerts.
**Phase 4:** Remaining platforms, comparable-title benchmarking, pre-release buzz index.

---

## 10. Success metrics

- **North star:** weekly active entities (titles + artists) with an owner who viewed the dashboard that week.
- Collection + analysis cost per tracked entity per day.
- Sentiment agreement rate vs human labels, code-mixed reported separately.
- Organic-vs-total mention ratio per title (a product metric *and* a sales talking point).
- Time-to-first-insight after creating a title (< 24h target).
- Pilot outcome: at least one production house uses the dashboard in a real campaign decision.

---

## 11. Immediate next steps

1. **Complete the T1–T7 spike battery** in Claude Code (~$0.16 of the $1.00 credit). T1a bare-`DC` baseline is the outstanding item — it quantifies the entity-resolution gap that justifies the rich title-setup flow.
2. **Run T3** on the collected corpus. This gate decides both the sentiment feature and the pricing model.
3. **Draft the entity model** — Title, Artist, Org, Membership, Tag — plus the collection-agent internal interface.
4. **Legal read** on scraping-sourced data for commercial analytics in India.
5. **Revise the UI brief.** Replace Reply Approval Queue with Artist Dashboard. Add account-type filter to Overview and Mentions Feed as a persistent control. Add Title Setup flow with alias suggestions. Keep Trend Detection and Influencer Discovery.
6. **Open items with Monid:** rate limits per key at surge cadence; server-side result caps on PER_RESULT endpoints; provider substitution behaviour if an endpoint goes down.
