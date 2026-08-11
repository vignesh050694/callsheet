### User Story E01-S05:

- **Summary:** Grant an agency access to one title only, so an external partner never sees the whole slate

**Epic:** E01 — Organizations, Access & Membership
**Phase:** 3
**Source:** Concept note §4 (P3, per-client access control)

#### Use Case:
- **As a** production house owner who has hired a social media agency for one film
- **I want to** grant that agency access scoped to that single title
- **so that** they can do their job without seeing my unannounced slate or my other films'
  performance

#### Acceptance Criteria:
- **Scenario:** Owner grants an agency manager access to one title out of several
- **Given:** my organization owns three titles, two of which are unannounced
- **and Given:** the agency already has its own organization on the platform
- **and Given:** the sharing screen requires me to pick specific titles rather than defaulting to all
- **and Given:** the "agency manager" role allows reading and exporting but not editing title setup
- **When:** I share exactly one title with the agency organization
- **Then:** the agency manager sees that single title in their client switcher and receives a
  404-equivalent on any direct link to my other two titles

#### Notes
- Enforcement must be at the query layer — a shared title grants no lateral visibility into the
  owning organization's member list or other entities.
- Every grant is written to an access audit log with actor, scope, and timestamp.

#### Out of scope
- The agency's own multi-client workspace UI (E07-S01).
- Agency-initiated access requests.
