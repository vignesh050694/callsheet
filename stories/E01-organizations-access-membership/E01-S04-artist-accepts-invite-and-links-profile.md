### User Story E01-S04:

- **Summary:** Accept a title invite and link my handles so my dashboard tracks the right person

**Epic:** E01 — Organizations, Access & Membership
**Phase:** 2
**Source:** Concept note §4 (P2), risk #7 (artist identity claims — invite-based linking in v1)

#### Use Case:
- **As an** actor invited onto a title by the production house
- **I want to** accept the invitation and confirm which social handles and name spellings are mine
- **so that** the perception I am shown is actually about me and not about someone with a similar
  name or a misspelt variant

#### Acceptance Criteria:
- **Scenario:** Artist accepts a title invitation and confirms their identity set
- **Given:** a production house has tagged me on a title and sent me an invitation
- **and Given:** the acceptance flow pre-fills the name variants and handles the production house
  entered for me
- **and Given:** I can add, correct, or remove any pre-filled variant before confirming
- **and Given:** the flow explains that the production house cannot see my personal dashboard
- **When:** I accept the invitation and confirm my corrected identity set
- **Then:** my artist entity is linked to my account, the corrected variants are used for entity
  matching from the next collection run onwards, and the title appears in my read-only list

#### Notes
- Corrections here feed the same alias set used by collection (E02-S04) — an artist fixing
  "Anirudh Ravichandran" vs "AnirudhRavichander" improves matching for everyone on the title.
- Identity is claimed by invitation only in v1; no self-serve "this is me" claim.

#### Out of scope
- Verified-badge style identity proof or document verification.
- Artist-initiated tracking of a title they were not invited to.
