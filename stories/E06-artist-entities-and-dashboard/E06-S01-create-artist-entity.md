### User Story E06-S01:

- **Summary:** Register an artist with every spelling of their name people actually use

**Epic:** E06 — Artist Entities & Artist Dashboard
**Phase:** 2
**Source:** Concept note §5.1, §6.1 (name variants in the wild: "Kankaraj", "Anirudh Ravichandran")

#### Use Case:
- **As an** artist manager setting up my client's profile
- **I want to** record every name spelling, handle, and nickname the audience uses for them
- **so that** their perception dashboard captures the whole conversation and not just the posts that
  happened to spell their name correctly

#### Acceptance Criteria:
- **Scenario:** Manager registers an artist whose name is routinely misspelt online
- **Given:** I am creating an artist entity within an organization
- **and Given:** the form captures the canonical name, alternate spellings, fan nicknames, and
  verified handles per platform
- **and Given:** the form warns me when a name variant is short or generic enough to collide with
  common words
- **and Given:** the artist can correct this set themselves when they accept their invite
- **When:** I save the artist with three name spellings and two platform handles
- **Then:** the artist entity is created with that combined identity set, which becomes the basis
  for matching mentions to them

#### Notes
- The live corpus contained "Kankaraj" for Kanagaraj and both "Anirudh Ravichandran" and
  "AnirudhRavichander" — misspellings are not edge cases in this market, they are the norm.
- Alias discovery (E02-S04) applies here too: variants found in the corpus should be suggested
  back for approval.

#### Out of scope
- Artist identity verification (invite-based linking only, risk #7).
- Tracking artists with no organization sponsoring them.
