# Epic E02 — Title Setup & Identity Discovery

**Phase:** 1
**Source:** Concept note §5.1, §6.1 (entity match validated at 20/20), §11.1, §11.5

## Epic hypothesis

**We believe that** making title identity rich at setup *and* continuously discovered from the corpus
**will result in** entity-match precision holding at or above 0.85 on anchored queries while catching
organic hashtags the studio never declared,
**We will know we are right when** a title's approved alias set contains at least one term the
production house did not enter at setup, and precision does not drop after that term is added.

## Why this epic exists

The live *DC* run proved two things at once:

1. The anchored query `"Lokesh Kanagaraj DC"` returned **20 of 20 relevant posts** — rich identity works,
   and justifies asking the production house to do real setup work.
2. Twenty posts alone surfaced seven organic hashtags (`#DCthemovie`, `#DCFDFS`, `#DCPublicReview`,
   `#DCTheBloodyValentineFromAugust7`, …) and misspelt name variants ("Kankaraj"). The identity set
   must be **discovered, not just declared**.

It also surfaced contamination inside an anchored query (`#DC #DareDevil` — the predicted DC Comics
bleed), which is why exclusion terms are a first-class setup control, not a support ticket.

## Personas served

- **P1 Production House** — does the setup, approves the suggestions.
- **P2 Artist** — corrections made at invite acceptance (E01-S04) flow into the same alias set.

## Stories

| ID | Summary | Phase |
|---|---|---|
| E02-S01 | Create a title with a rich identity set | 1 |
| E02-S02 | Anchor the title to a release date and campaign milestones | 1 |
| E02-S03 | Preview live sample results before committing setup | 1 |
| E02-S04 | Review and approve discovered alias suggestions | 1 |
| E02-S05 | Exclude a contaminating term from a title's results | 1 |

## Dependencies

- **Blocked by:** E01 (a title belongs to an org).
- **Blocks:** E03 (nothing to collect without an identity set), E05 (pre/post release split needs §E02-S02).

## Gate this epic is measured against

> Entity-match precision on anchored query **≥ 0.85** — *provisionally met at 1.00* (concept note §9).

## Out of scope

- Automatic title creation from a trade announcement feed.
- Comparable-title benchmarking (Phase 4).
