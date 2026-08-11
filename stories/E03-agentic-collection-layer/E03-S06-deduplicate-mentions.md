### User Story E03-S06:

- **Summary:** Count one conversation once, so overlapping queries don't inflate my volume

**Epic:** E03 — Agentic Collection Layer
**Phase:** 1
**Source:** Concept note §6 (pipeline: ingest → dedupe → entity match)

#### Use Case:
- **As a** production house owner whose title is tracked through five overlapping query variants
- **I want to** have the same post counted only once no matter how many queries returned it
- **so that** my mention volume is a real measure of conversation rather than a measure of how many
  search terms I configured

#### Acceptance Criteria:
- **Scenario:** The same post is returned by several query variants in one polling cycle
- **Given:** my title runs five query variants per platform per poll
- **and Given:** a single popular post matches three of those variants
- **and Given:** deduplication keys on platform plus native post ID
- **and Given:** the retained record preserves which query variants matched it
- **When:** the polling cycle completes and the pipeline runs
- **Then:** the post contributes exactly one mention to volume, sentiment, and every chart, while
  the matched-variant list is retained for alias-discovery analysis

#### Notes
- Verbatim reposts/retweets are a separate, deliberate decision: they are distinct posts by
  distinct authors and should be counted, but flagged as amplification so E05 can show
  "conversations vs amplifications".
- Near-duplicate promotional text posted by many cinema chains is handled by account-type
  classification (E04-S03), not by dedupe.

#### Out of scope
- Cross-platform identity resolution (the same person posting on X and Instagram).
- Semantic near-duplicate clustering.
