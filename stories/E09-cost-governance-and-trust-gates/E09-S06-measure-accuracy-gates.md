### User Story E09-S06:

- **Summary:** Measure every number against human labels before we let a customer see it

**Epic:** E09 — Cost Governance & Trust Gates
**Phase:** 1
**Source:** Concept note §9 (gate table), §10 (agreement rate, code-mixed reported separately), §11.2

#### Use Case:
- **As a** product owner deciding whether Phase 1 can ship its sentiment number
- **I want to** measure sentiment agreement, account-type accuracy, and entity-match precision
  against a human-labelled sample, with the code-mixed subset reported separately
- **so that** the decision to show or withhold a number rests on a measurement rather than on
  how the dashboard feels to look at

#### Acceptance Criteria:
- **Scenario:** Product owner reviews gate results before the Phase 2 decision
- **Given:** a human-labelled evaluation sample has been drawn from a real title's corpus, stratified
  by language and account type
- **and Given:** an internal evaluation view reports sentiment agreement, account-type accuracy, and
  entity-match precision against the §9 thresholds
- **and Given:** sentiment agreement is broken out for the code-mixed subset separately from English
- **and Given:** each result names the pipeline version and models that produced it
- **When:** I open the evaluation view after a labelling round
- **Then:** I see each metric against its threshold with a clear pass or fail, including a separate
  pass or fail for the code-mixed subset

#### Notes
- Thresholds: sentiment agreement **≥ 0.75**; account-type accuracy **≥ 0.85**; entity-match
  precision **≥ 0.85** (provisionally met at 1.00 on the anchored query).
- An overall pass that hides a code-mixed failure is the exact outcome the separate reporting rule
  exists to prevent — a 0.80 overall built from 0.90 English and 0.55 Tamil is a fail.
- Customer corrections made in the mentions feed (E05-S05) should feed the labelled pool; they are
  the cheapest labels available.
- Re-running evaluation is free of collection cost thanks to E03-S04 and E04-S07.

#### Out of scope
- Continuous automated retraining from corrections.
- Publishing accuracy figures externally.
