### User Story E01-S03:

- **Summary:** Tag a cast member on a title and invite them so the star sees their own coverage

**Epic:** E01 — Organizations, Access & Membership
**Phase:** 2
**Source:** Concept note §4 (P1 invites tagged artists), §5.6

#### Use Case:
- **As a** production house owner whose lead actor keeps asking how the film is landing online
- **I want to** tag that actor on the title and send them an invitation
- **so that** they can watch the conversation about the film themselves instead of routing every
  question through my team

#### Acceptance Criteria:
- **Scenario:** Owner tags the lead actor on a title and invites them
- **Given:** I own a title that has an active collection running
- **and Given:** the title's cast list includes the actor I want to tag
- **and Given:** the artist has an email address or verified handle I can send an invitation to
- **and Given:** the tagging screen states that a tagged artist sees only mentions of the title
  that also mention them
- **When:** I tag the actor on the title and send the invitation
- **Then:** the actor receives an invitation, and a pending "tagged artist" membership appears on
  the title showing the restricted scope they will get

#### Notes
- The membership is created in `pending` state; no data is exposed until acceptance (E01-S04).
- Tagging is reversible — untagging removes the membership and revokes access immediately.

#### Out of scope
- The Artist Dashboard itself (E06) — this story only creates the relationship.
- Automatic detection of who should be tagged from the cast list.
