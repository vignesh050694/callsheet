### User Story E01-S06:

- **Summary:** Revoke a partner's access the day the contract ends, with immediate effect

**Epic:** E01 — Organizations, Access & Membership
**Phase:** 3
**Source:** Concept note §4 (Memberships), risk #1 (data handling under legal review)

#### Use Case:
- **As a** production house owner whose agency contract has ended
- **I want to** revoke that agency's access in one action and see it take effect immediately
- **so that** a former partner cannot keep watching my film's performance after the engagement
  is over

#### Acceptance Criteria:
- **Scenario:** Owner revokes an agency membership while the agency has the dashboard open
- **Given:** an agency organization currently has manager access to one of my titles
- **and Given:** an agency user has that title's dashboard open in their browser
- **and Given:** the Members screen shows a "Revoke access" action for each external membership
- **and Given:** revocation is confirmed with a dialog naming the organization losing access
- **When:** I confirm the revocation
- **Then:** the agency user's next request fails authorization and they are returned to their
  client list with the title gone, with the revocation recorded in the access audit log

#### Notes
- Applies identically to tagged artists and internal viewers.
- Previously exported reports are not recalled — this is stated in the confirmation dialog so the
  owner is not misled about what revocation does.

#### Out of scope
- Scheduled/expiring access grants.
- Retroactive deletion of exports already downloaded by the partner.
