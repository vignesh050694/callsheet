### User Story E05-S05:

- **Summary:** Read the actual posts behind any number and open the original

**Epic:** E05 — Title Dashboard
**Phase:** 1
**Source:** Concept note §11.5 (Mentions Feed with persistent account-type control), §9

#### Use Case:
- **As a** production house marketing head who has just seen sentiment drop
- **I want to** click into the underlying mentions and open the original posts
- **so that** I can verify what people actually said before I take a number into a meeting with
  my director

#### Acceptance Criteria:
- **Scenario:** Owner drills from a sentiment dip into the posts that caused it
- **Given:** the sentiment trend shows a decline on a specific day
- **and Given:** every chart point is clickable through to a filtered Mentions Feed
- **and Given:** each feed row shows author, handle, follower count, timestamp, platform, detected
  language, account type, sentiment, engagement counts, and a link to the original post
- **and Given:** the feed inherits the active account-type filter and adds date, platform,
  language, and sentiment filters of its own
- **When:** I click the day where sentiment declined
- **Then:** I see the mentions from that day in that scope, and can open any one of them on its
  source platform in a new tab

#### Notes
- Every classification shown in a row must be visible, because this feed is where a customer
  first discovers a misclassification — and the correction path (E09-S06) starts here.
- Retain the original text verbatim; do not normalise or truncate code-mixed text in a way that
  makes it unrecognisable to a native reader.

#### Out of scope
- Replying, liking, or any engagement action from the feed (v1 is read-only by design).
- Saved searches and personal bookmarks.
