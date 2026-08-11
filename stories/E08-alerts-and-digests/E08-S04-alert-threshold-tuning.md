### User Story E08-S04:

- **Summary:** Tune my alerts so a tentpole release doesn't bury me and an indie release isn't silent

**Epic:** E08 — Alerts & Digests
**Phase:** 3
**Source:** Concept note §7 (volume varies 10–20× between titles), §5.5

#### Use Case:
- **As a** production house marketing head tracking both a tentpole and a small release
- **I want to** set alert sensitivity per entity
- **so that** the big title does not flood my inbox while the small one never triggers anything at all

#### Acceptance Criteria:
- **Scenario:** Owner tunes alert sensitivity separately for two titles of very different scale
- **Given:** I own a high-volume title and a low-volume title
- **and Given:** each entity has its own alert settings with sensitivity, quiet hours, and channel
- **and Given:** default sensitivity is derived from the entity's own observed baseline rather than
  a fixed global number
- **and Given:** the settings screen shows how many alerts each setting would have produced over
  the last 14 days
- **When:** I lower sensitivity on the tentpole title
- **Then:** its alert volume drops as previewed, while the smaller title's settings are unaffected

#### Notes
- The "how many alerts would this have sent" preview is what makes tuning possible without a week
  of trial and error, and it can be computed from stored data at no collection cost (E03-S04).
- Baseline-relative defaults matter because mention volume for a tentpole is plausibly 10–20× a
  mid-budget film (§7) — one global threshold cannot serve both.

#### Out of scope
- Machine-learned personalisation of alert relevance.
- Per-recipient thresholds within one organization.
