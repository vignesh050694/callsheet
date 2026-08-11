### User Story E02-S01:

- **Summary:** Describe a title richly at setup so collection finds the film and not its namesakes

**Epic:** E02 — Title Setup & Identity Discovery
**Phase:** 1
**Source:** Concept note §5.1, §6.1 (rich identity produced 20/20 precision)

#### Use Case:
- **As a** production house owner adding a film whose short title is an ordinary word
- **I want to** enter the title's aliases, official hashtags, and lead cast and crew alongside the name
- **so that** the system tracks conversation about *my* film rather than everything that shares
  its name

#### Acceptance Criteria:
- **Scenario:** Owner sets up a two-letter title that collides with a global franchise
- **Given:** I am an owner in a production house organization
- **and Given:** the setup form has fields for title name, alternate names, official hashtags,
  lead cast, director, and music director
- **and Given:** the form explains that a short or generic name needs at least one anchor term
  (a cast or crew name) to be collectable
- **and Given:** the form blocks submission of a name under four characters with no anchor term
- **When:** I enter the title name, its official hashtags, and the director and lead cast, and save
- **Then:** the title is created with a stored identity set combining name, aliases, hashtags,
  and people, and that combined set — not the bare name — is what collection queries against

#### Notes
- The live run showed a bare-title query is the failure case; the anchored form of the same query
  returned 20/20 relevant posts. The form's job is to make the anchored form unavoidable.
- Poster/thumbnail/cover assets are captured here and reused as dashboard identity.

#### Out of scope
- Alias *discovery* from the corpus (E02-S04) — this story covers only what the studio declares.
- Cast members as tracked artist entities (E06-S01).
