### User Story E05-S06:

- **Summary:** See the handful of posts and accounts actually moving the conversation

**Epic:** E05 — Title Dashboard
**Phase:** 1
**Source:** Concept note §9 (top posts), §11.5 (keep Influencer Discovery)

#### Use Case:
- **As a** production house marketing head with limited attention on release weekend
- **I want to** see the highest-reach posts and the accounts driving the most conversation about
  my title
- **so that** I can decide what to amplify and who is worth engaging, without scrolling a feed of
  thousands

#### Acceptance Criteria:
- **Scenario:** Owner reviews the top posts of release weekend
- **Given:** my title has a release-weekend corpus with engagement counts and follower data
- **and Given:** the Overview has a top posts panel ranked by engagement and a top voices panel
  ranked by reach-weighted contribution
- **and Given:** both panels respect the active account-type filter
- **and Given:** each entry shows its account type explicitly
- **When:** I open the top posts panel for release weekend
- **Then:** I see the ranked posts with their author, account type, engagement, and a link to the
  original, so I can tell an organic hit apart from my own distributor's promotion at a glance

#### Notes
- Without the account-type label, this panel would be dominated by owned and promotional accounts
  — which is exactly the failure mode §6.3 describes.
- Media-only posts frequently top this list; they belong here even though they carry no sentiment.

#### Out of scope
- Influencer outreach execution or contact management (explicitly out of scope for v1, §5).
- Paid amplification actions.
