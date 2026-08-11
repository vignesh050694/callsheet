### User Story E07-S03:

- **Summary:** Be certain a competing client's numbers can never leak into my other client's view

**Epic:** E07 — Agency Workspace & Multi-Client Reporting
**Phase:** 3
**Source:** Concept note §4 (per-client access control), §8 risk #1 (data handling under legal review)

#### Use Case:
- **As an** agency owner whose roster includes two studios releasing competing films
- **I want to** be certain that each client's data is isolated from the other in every view, export,
  and alert
- **so that** I can take on competing clients without risking the relationship-ending mistake of
  showing one their rival's numbers

#### Acceptance Criteria:
- **Scenario:** Two competing clients are managed from the same agency workspace
- **Given:** my agency holds grants on entities from two competing studios
- **and Given:** every data query is scoped by the active client grant at the query layer, not by
  UI filtering
- **and Given:** exports, digests, and alerts each carry a single client scope
- **and Given:** an entity whose grant has been revoked is excluded immediately from every surface
  including scheduled reports
- **When:** any dashboard, export, or scheduled report is generated for one client
- **Then:** it contains only that client's entities, verified by the scope stamped on the artefact
  itself, with cross-client access attempts denied and logged

#### Notes
- Treat this as a security story with tests, not a UI story: authorization must be provable at the
  data-access layer and covered by automated tests for every read path.
- Scheduled artefacts (E07-S04, E08) are the likeliest leak vector, because they are generated
  after the grant that authorised them may have changed.

#### Out of scope
- Formal certification (SOC 2 and equivalents) — separate track.
- Customer-managed encryption keys.
