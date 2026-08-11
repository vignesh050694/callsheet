### User Story E03-S05:

- **Summary:** Tell me when a platform stops reporting, instead of showing a flat line as if it's calm

**Epic:** E03 — Agentic Collection Layer
**Phase:** 1
**Source:** Concept note §6.4 (label gaps rather than hide them), §8 risk #5 (Monid dependency)

#### Use Case:
- **As a** production house owner reading a dashboard on release weekend
- **I want to** be told when a platform's collection has failed or gone stale
- **so that** I never mistake a broken pipe for a quiet audience and make a campaign decision on
  a number that stopped updating

#### Acceptance Criteria:
- **Scenario:** One platform's endpoint fails during release weekend
- **Given:** my title collects from X, Reddit, YouTube, and Instagram
- **and Given:** the dashboard header shows a per-platform last-successful-collection time
- **and Given:** a platform is considered stale when it has missed the expected interval for its
  current cadence phase
- **and Given:** stale platforms are excluded from "as of" freshness claims
- **When:** Instagram collection fails repeatedly through the surge window
- **Then:** the dashboard shows Instagram as stale with its last successful time, and every chart
  containing Instagram data carries a visible warning that the platform is not currently reporting

#### Notes
- Concept note §6.4 sets the house rule: label the coverage gap in the UI rather than hiding it.
  This story applies that rule to collection failures, E05-S08 applies it to analysis gaps.
- Repeated failures should raise an internal alert to data ops before the customer notices.

#### Out of scope
- Automatic failover to an alternative provider (E03-S07).
- Customer-facing SLA commitments on freshness.
