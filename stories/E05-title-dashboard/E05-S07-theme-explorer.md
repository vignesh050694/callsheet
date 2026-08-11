### User Story E05-S07:

- **Summary:** See what the conversation is about and how those subjects move week to week

**Epic:** E05 — Title Dashboard
**Phase:** 1
**Source:** Concept note §5.3, §9, §11.5 (keep Trend Detection)

#### Use Case:
- **As a** production house marketing head shaping the second week's messaging
- **I want to** see which subjects the audience keeps returning to and whether each is rising or fading
- **so that** I can push the parts of the film people are already praising instead of guessing at
  what to cut a promo around

#### Acceptance Criteria:
- **Scenario:** Owner reviews themes to plan week-two messaging
- **Given:** my title has extracted themes across at least two weeks of conversation
- **and Given:** the Themes view lists themes ranked by volume with direction of change against the
  prior period
- **and Given:** each theme shows its account-type mix and links to its mentions
- **and Given:** the view respects the active account-type filter
- **When:** I open the Themes view and compare this week to last
- **Then:** I see which themes grew and which faded, and can click any theme to read the mentions
  behind it

#### Notes
- This view must stand on its own with sentiment removed — it is a core part of the §9 fallback
  product if the sentiment gate fails.
- A theme that is large only among trade accounts is a different signal from one large among the
  audience; the account-type mix per theme is what makes that visible.

#### Out of scope
- Theme-level sentiment scoring where the sentiment gate has not been cleared for that language.
- Custom theme definitions authored by the customer.
