### User Story E09-S03:

- **Summary:** Have a server-side spend ceiling that stops runs even when our own code is wrong

**Epic:** E09 — Cost Governance & Trust Gates
**Phase:** 1
**Source:** Concept note §7 cost-control rule 4 ("that's the real safety net"), §8 risk #2

#### Use Case:
- **As an** internal data ops engineer
- **I want to** have spend controls configured server-side in the provider workspace, outside our
  own application
- **so that** a bug in our scheduler or a runaway loop in our agent hits a ceiling we do not control
  and cannot accidentally bypass

#### Acceptance Criteria:
- **Scenario:** A scheduling bug drives collection far past the intended cadence
- **Given:** workspace spend controls are configured with daily and monthly ceilings
- **and Given:** a run blocked by a control returns `BLOCKED` with a reason
- **and Given:** our collection layer treats `BLOCKED` as a terminal, non-retryable outcome
- **and Given:** a `BLOCKED` result raises an operational alert immediately
- **When:** a scheduling fault causes collection to exceed the daily ceiling
- **Then:** further runs return `BLOCKED` and stop rather than retrying, and affected titles show a
  collection-stale state per E03-S05 rather than appearing quiet

#### Notes
- The failure mode this guards against is our own code, which is why the ceiling must live in the
  provider workspace rather than in our application config.
- Retrying a `BLOCKED` run is the single worst thing the agent could do — it converts a safety net
  into a tight loop. Treat it as terminal and cover it with a test.
- The customer-facing consequence must be honest: a title stopped by a spend control shows as stale,
  never as a quiet audience.

#### Out of scope
- Per-customer spend ceilings surfaced in the product UI (E09-S04 covers visibility, E09-S05 pricing).
