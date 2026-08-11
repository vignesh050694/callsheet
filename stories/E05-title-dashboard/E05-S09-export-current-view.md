### User Story E05-S09:

- **Summary:** Export the view I'm looking at, with its scope and caveats attached

**Epic:** E05 — Title Dashboard
**Phase:** 1
**Source:** Concept note §3 (studios live on circulated reports), §4 (P3 exportable reports), §6.4

#### Use Case:
- **As a** production house marketing head who has to brief people who will never log in
- **I want to** export the current dashboard view as a shareable file
- **so that** I can put it in front of my producer and distributor without them having to be given
  an account

#### Acceptance Criteria:
- **Scenario:** Owner exports release-week performance for a producer briefing
- **Given:** I am viewing my title's dashboard for a chosen date range with an account-type filter applied
- **and Given:** the dashboard offers an export action producing PDF and CSV
- **and Given:** the export records the title, date range, active account-type scope, per-platform
  freshness, and the coverage-gap disclosure
- **and Given:** CSV export contains the underlying mentions for the active scope
- **When:** I export the current view
- **Then:** I receive a file whose numbers match what is on screen and which carries its own scope
  and caveats, so it cannot be read out of context once it leaves my hands

#### Notes
- An export stripped of its account-type scope becomes exactly the misleading artefact §6.3 warns
  about, one that then circulates through a studio unchallenged. The scope label is not decoration.
- Exports are not recalled when access is revoked (E01-S06) — say so where access is granted.

#### Out of scope
- Branded/white-label report templates (E07-S04, agency phase).
- Scheduled recurring exports (E08-S01 digests cover the recurring case).
