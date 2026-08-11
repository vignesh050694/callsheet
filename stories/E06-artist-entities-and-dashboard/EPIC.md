# Epic E06 — Artist Entities & Artist Dashboard

**Phase:** 2
**Source:** Concept note §4 (P2 + validated complication), §5.1, §9 (Phase 2), §11.5

## Epic hypothesis

**We believe that** giving artists their own perception dashboard, with a filter that separates the
different roles they occupy in a conversation
**will result in** artists having an independent view of their public perception that they trust more
than an agency summary,
**We will know we are right when** tagged artists become a meaningful share of weekly active entities
with an owner who viewed them.

## Why this epic exists

Artists have no independent view of their own public perception — they receive it filtered through
agencies and studios.

The live corpus turned this from a persona statement into a hard, testable requirement. In the *DC*
data, **Lokesh Kanagaraj appears simultaneously as three different things**:

1. the film's **lead actor**,
2. a celebrated **director** whose brand the film is boosting,
3. an **upcoming collaborator** on an unrelated Allu Arjun project (`#AA23`) that surfaces inside
   DC-anchored results.

Mixing those three into one "perception score" produces a number about nothing. The Artist Dashboard's
core filter is separating them — this is the epic's defining feature, not a refinement.

## Personas served

- **P2 Actor / Artist** — the dashboard owner.
- **P1 Production House** — tags artists, but does not see their personal dashboard.

## Stories

| ID | Summary | Phase |
|---|---|---|
| E06-S01 | Create an artist entity with a rich identity set | 2 |
| E06-S02 | See my own perception dashboard | 2 |
| E06-S03 | Separate mentions of me by the role I'm playing in them | 2 |
| E06-S04 | See a tagged title filtered to conversation that mentions me | 2 |
| E06-S05 | Keep my personal dashboard private from the studio that tagged me | 2 |

## Dependencies

- **Blocked by:** E01-S03 / E01-S04 (tagging and invite acceptance), E04, E05 (component reuse).

## Out of scope

- Artist-initiated tracking without a studio invite.
- Personal brand recommendations or content advice.
- Any posting or reply capability.
