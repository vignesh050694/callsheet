### User Story E01-S02:

- **Summary:** Invite a teammate with a role so campaign staff can read the dashboard without sharing a login

**Epic:** E01 — Organizations, Access & Membership
**Phase:** 1
**Source:** Concept note §4 (Memberships: owner, viewer)

#### Use Case:
- **As a** production house owner running a release campaign
- **I want to** invite my publicity and digital team members as viewers on my organization
- **so that** they can read the same numbers I do without me forwarding screenshots or sharing
  my own credentials

#### Acceptance Criteria:
- **Scenario:** Owner invites a publicity manager as a viewer
- **Given:** I am the owner of a production house organization
- **and Given:** my colleague's work email address is not yet a member of my organization
- **and Given:** the Members screen offers the roles "Owner" and "Viewer"
- **and Given:** an invited viewer inherits read access to every title in the organization
- **When:** I enter my colleague's email, select "Viewer", and send the invitation
- **Then:** my colleague receives an invitation email and, on accepting, sees my organization's
  titles in read-only mode with no ability to edit title setup or delete data

#### Notes
- Pending invitations are listed on the Members screen with the ability to resend or cancel.
- Viewer role must be enforced server-side, not only by hiding UI controls.

#### Out of scope
- Per-title roles within an organization (org-level roles only in v1).
- Agency manager role (E01-S05) and tagged artist role (E01-S03).
