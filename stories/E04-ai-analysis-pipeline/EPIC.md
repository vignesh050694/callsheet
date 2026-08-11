# Epic E04 — AI Analysis Pipeline

**Phase:** 1
**Source:** Concept note §5.3, §6.2, §6.3, §6.4, §7 (analysis is the budget risk), §9 gates

## Epic hypothesis

**We believe that** running language ID and account-type classification *before* sentiment
**will result in** a sentiment number that reflects genuine audience opinion in the language it was
actually written in,
**We will know we are right when** sentiment agreement vs human labels reaches **≥ 0.75** with the
code-mixed subset reported separately, and account-type classification accuracy reaches **≥ 0.85**.

## Why this epic exists

v0.1's pipeline was `ingest → dedupe → entity match → sentiment → aggregate`. Live data proved that
wrong in two places. The revised pipeline is:

```
ingest → dedupe → entity match → LANGUAGE ID → ACCOUNT-TYPE CLASSIFY
       → sentiment (routed by language) → theme extraction → aggregate
```

**Language ID is mandatory, not optional.** Roughly half the non-English content in the live sample
was mislabelled by the platform itself — Telugu in Latin script tagged `en`, Tamil tagged `in`
(Indonesian), `ht` (Haitian Creole), and `fi` (Finnish). Routing on the platform tag sends code-mixed
content to an English sentiment model, which is precisely the failure this product exists to avoid.

**Account-type classification is the product wedge.** The *DC* corpus mixes organic audience, trade
and tracker accounts, owned media, and promotional accounts. Averaging across all four measures
campaign activity, not public opinion — a production house reading its own press back to itself.

## Personas served

- **P1 / P2 / P3** — every dashboard number depends on this epic being right.
- **Internal Data Ops** — owns model choice, cost, and the gate measurements.

## Stories

| ID | Summary | Phase |
|---|---|---|
| E04-S01 | Identify the real language, ignoring the platform's tag | 1 |
| E04-S02 | Route sentiment by detected language | 1 |
| E04-S03 | Classify every mention's account type | 1 |
| E04-S04 | Extract the themes people are actually talking about | 1 |
| E04-S05 | Detect spikes and explain them against campaign dates | 1 |
| E04-S06 | Count media-only posts in volume but exclude them from sentiment | 1 |
| E04-S07 | Swap analysis models behind one interface and compare versions | 1 |

## Dependencies

- **Blocked by:** E03 (needs a corpus), especially E03-S04 (reprocessing is how this epic iterates).
- **Blocks:** E05, E08.
- **Coupled to:** E09-S06 / E09-S07 (the gates and the fail-safe).

## The cost coupling to state plainly

> "The code-mixed problem and the budget problem are the same problem."

Analysis of 500K–2M mentions batched at 50/call costs ~**$90** on a small/fast model and ~**$900** on
a frontier-tier model. If off-the-shelf sentiment fails on Tamil-in-Latin-script, we are pushed up the
model ladder and a single title approaches **$1,200** all-in. Every story in this epic should be built
so the cheapest model that clears the gate can be used, per language.

## Out of scope

- Multimodal (video/image) sentiment — v1 discloses the gap (E04-S06, E05-S08).
- Sarcasm/irony detection as a named feature.
