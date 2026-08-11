### User Story E06-S05:

- **Summary:** Keep my personal perception dashboard invisible to the studio that tagged me

**Epic:** E06 — Artist Entities & Artist Dashboard
**Phase:** 2
**Source:** Concept note §4 (P2 personal dashboard vs P1 tagging), risk #7

#### Use Case:
- **As an** actor who accepted a studio's invitation to a title
- **I want to** know for certain that the studio can see the title's data but not my personal
  perception dashboard
- **so that** I can use the tool honestly without worrying that my own reputation data is being read
  by the people who hired me

#### Acceptance Criteria:
- **Scenario:** A production house owner attempts to view a tagged artist's personal dashboard
- **Given:** I am an artist tagged on a production house's title
- **and Given:** my artist entity has its own personal dashboard scoped to my account
- **and Given:** the production house's member list shows my tagged membership but exposes no link
  into my personal dashboard
- **and Given:** the boundary is stated in plain language in both the invite flow and the studio's
  tagging screen
- **When:** the production house owner requests my artist entity directly by its identifier
- **Then:** the request is denied by authorization, and the studio sees only the title-scoped
  intersection data they already own

#### Notes
- This has to be enforced server-side and be stated in the product copy — the promise is worthless
  to the artist if they cannot see it written down before accepting.
- If an artist entity was created *by* an agency or studio on the artist's behalf (E06-S01), the
  transition of ownership at invite acceptance must be explicit about what the creator retains.

#### Out of scope
- Artist-configurable sharing of their personal dashboard with a chosen party.
- Data deletion requests (handle under the §11.4 legal review).
