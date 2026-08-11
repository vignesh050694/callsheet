### User Story E03-S03:

- **Summary:** Backfill the weeks before I signed up, so my trailer launch isn't a blank spot

**Epic:** E03 — Agentic Collection Layer
**Phase:** 1
**Source:** Concept note §2 (working pagination cursor), §7 (pagination depth drives PER_CALL cost)

#### Use Case:
- **As a** production house owner who onboards mid-campaign, after the teaser and trailer are out
- **I want to** pull the conversation from a past date range into my title
- **so that** my dashboard shows the campaign I actually ran rather than starting from the day I
  happened to sign up

#### Acceptance Criteria:
- **Scenario:** Owner backfills from the trailer launch date onwards
- **Given:** my title was created after my trailer had already launched
- **and Given:** the Title Dashboard offers a "Backfill history" action with a date range
- **and Given:** the backfill screen shows the estimated cost and page depth before I confirm
- **and Given:** the estimate is derived from PER_CALL pricing and a hard page cap
- **When:** I select a date range starting at my trailer launch and confirm the backfill
- **Then:** historical mentions in that range are collected and merged into my existing trend
  charts, marked as backfilled, without duplicating anything already collected

#### Notes
- Backfill depth is bounded by what the underlying search endpoints will return, which is not the
  same as the requested range — the UI must state the depth actually achieved, not silently
  return less than asked for.
- Cost estimate must respect §7 rule 2: pagination depth is the cost driver on PER_CALL endpoints.

#### Out of scope
- Guaranteed completeness of historical data (platform search depth limits make this impossible
  to promise — say so in the UI).
- Backfilling deleted posts.
