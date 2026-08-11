### User Story E02-S03:

- **Summary:** See real sample posts before committing setup, so I trust the tracker from minute one

**Epic:** E02 — Title Setup & Identity Discovery
**Phase:** 1
**Source:** Concept note §6.1, §7 (a preview costs ~$0.0015), §10 (time-to-first-insight < 24h)

#### Use Case:
- **As a** production house owner who has just typed in my title's identity set
- **I want to** see a handful of real posts that my setup would collect, before I finish setup
- **so that** I find out immediately if I have described my film badly, rather than discovering
  a junk dashboard a day later

#### Acceptance Criteria:
- **Scenario:** Owner previews results and spots contamination before saving
- **Given:** I have entered a title name, at least one anchor term, and at least one hashtag
- **and Given:** the setup screen offers a "Preview matches" action
- **and Given:** a preview runs a single capped search and returns at most 20 recent posts
- **and Given:** each previewed post shows author, text, and why it matched
- **When:** I run the preview
- **Then:** I see the sample posts within seconds and can mark any of them "not my title" before
  saving, which seeds the title's exclusion terms

#### Notes
- Preview must use a PER_CALL endpoint with a single page — a preview that can run away on cost
  is a preview we cannot offer for free (§7 cost-control rule 2).
- Preview results are discarded, not stored as mentions; collection proper starts at E03-S01.

#### Out of scope
- Precision scoring or a numeric quality grade on the preview.
- Previewing across all four platforms — one platform (X) is enough to catch a bad identity set.
