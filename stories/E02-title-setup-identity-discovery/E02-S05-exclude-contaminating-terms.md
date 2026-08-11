### User Story E02-S05:

- **Summary:** Exclude a colliding term so unrelated franchise chatter stops polluting my numbers

**Epic:** E02 — Title Setup & Identity Discovery
**Phase:** 1
**Source:** Concept note §6.1 (`#DC #DareDevil` contamination confirmed inside an anchored query)

#### Use Case:
- **As a** production house owner whose title's short name collides with a global comics franchise
- **I want to** add exclusion terms that disqualify a post from my title
- **so that** my volume and sentiment numbers describe my film and not a superhero conversation
  that happens to share three letters

#### Acceptance Criteria:
- **Scenario:** Owner excludes a colliding franchise term after seeing it in the mentions feed
- **Given:** my title's mentions feed contains posts tagged with an unrelated franchise
- **and Given:** every post in the feed has a "Not my title" action
- **and Given:** using that action offers to exclude the specific term that caused the match
- **and Given:** the exclusion screen shows how many already-collected mentions the rule would remove
- **When:** I confirm the exclusion term
- **Then:** matching mentions are removed from all counts and charts for this title from that point
  on, historic mentions included, and future collection stops matching them

#### Notes
- Exclusions apply at entity-match time, so the underlying raw payload is retained (E03-S04) and
  the rule can be undone without re-paying for collection.
- Show the removal count *before* confirming — a broad exclusion term can silently delete a large
  share of a title's corpus.

#### Out of scope
- Account-level exclusions (that is account-type classification, E04-S03).
- Regex or boolean query authoring for end users.
