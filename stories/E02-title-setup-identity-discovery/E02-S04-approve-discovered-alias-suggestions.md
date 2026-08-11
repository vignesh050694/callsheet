### User Story E02-S04:

- **Summary:** Approve hashtags the audience invented, so tracking follows the conversation as it mutates

**Epic:** E02 — Title Setup & Identity Discovery
**Phase:** 1
**Source:** Concept note §6.1 ("alias discovery is a feature, not a setup field"), §9 (MVP scope)

#### Use Case:
- **As a** production house owner whose fans keep coining new hashtags
- **I want to** be shown hashtags and name variants that co-occur with my title and approve the
  real ones
- **so that** I capture the FDFS and review waves that trend under tags nobody on my team could
  have predicted at setup

#### Acceptance Criteria:
- **Scenario:** Owner reviews organically-emerged hashtags after a review wave
- **Given:** my title has been collecting for at least one polling cycle
- **and Given:** the corpus contains hashtags and name spellings not in my declared identity set
- **and Given:** the Title Setup screen has an "Alias suggestions" list showing each candidate with
  its mention count, a sample post, and Approve / Reject actions
- **and Given:** rejected candidates are remembered and never re-suggested for this title
- **When:** I approve a suggested hashtag
- **Then:** it joins the title's identity set, is used by the next collection run, and previously
  collected posts carrying it are re-matched to the title without paying to re-collect them

#### Notes
- Twenty posts from one live run produced seven distinct organic hashtags — the suggestion list
  will be busy early in a campaign and must rank by volume, not recency.
- Re-matching stored raw payloads depends on E03-S04.
- Misspellings ("Kankaraj") are as valuable as hashtags — the candidate miner must cover both.

#### Out of scope
- Auto-approving suggestions above a volume threshold (v1 keeps a human in the loop).
- Suggesting aliases across titles in the same franchise.
