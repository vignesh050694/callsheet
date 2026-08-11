### User Story E06-S02:

- **Summary:** See how the public sees me, without it being filtered by anyone first

**Epic:** E06 — Artist Entities & Artist Dashboard
**Phase:** 2
**Source:** Concept note §3 ("no independent view of their own public perception"), §4 P2

#### Use Case:
- **As an** actor whose only picture of public opinion comes from my agency's summaries
- **I want to** see my own volume, sentiment, themes, and notable posts in one place
- **so that** I can form my own view of how I am perceived rather than the view someone else has
  decided to show me

#### Acceptance Criteria:
- **Scenario:** Artist opens their personal dashboard for the first time
- **Given:** I have an artist entity linked to my account with collection running
- **and Given:** my dashboard shows volume trend, sentiment trend, themes, and notable posts about me
- **and Given:** the same organic-audience default and account-type filter apply as on a title
- **and Given:** the same coverage-gap disclosure appears alongside my sentiment number
- **When:** I open my Artist Dashboard
- **Then:** I see my perception over time computed from organic audience mentions by default, with
  the same honesty about what was and was not scored that a production house gets

#### Notes
- The organic-only default matters more here than anywhere: a sentiment score inflated by fan-club
  and promotional accounts is precisely the flattering distortion this persona is trying to escape.
- Component reuse from E05 is deliberate — this dashboard should not diverge into a second
  codebase of charts.

#### Out of scope
- Comparisons against other artists.
- Reputation "scores" or ranks.
