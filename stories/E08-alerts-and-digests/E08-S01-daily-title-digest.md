### User Story E08-S01:

- **Summary:** Get yesterday's conversation in my inbox before my first meeting

**Epic:** E08 — Alerts & Digests
**Phase:** 1
**Source:** Concept note §5.5, §9 (MVP: daily email digest), §10 (north star)

#### Use Case:
- **As a** production house marketing head with a full day of meetings
- **I want to** receive a short daily email summarising my title's last 24 hours
- **so that** I walk into my morning meeting already knowing what happened, without having to
  remember to open a dashboard

#### Acceptance Criteria:
- **Scenario:** Owner receives the morning digest during release week
- **Given:** I own a title with active collection
- **and Given:** the digest sends once a day at a time I choose, in my timezone
- **and Given:** it contains volume vs the previous day, organic sentiment direction, the top three
  themes, the top three posts, and any spikes detected
- **and Given:** every figure states the account-type scope it was computed under
- **and Given:** each section links directly into the matching dashboard view
- **When:** the digest sends for a day with a large overnight volume increase
- **Then:** I receive an email leading with the increase and its likely driver, from which one click
  takes me to the mentions behind it

#### Notes
- The digest is the north-star lever, so its click-through into the dashboard should be measured
  from day one.
- If sentiment is suppressed for this title (E09-S07), the digest omits the sentiment line entirely
  rather than sending a blank or a placeholder.
- A day with no meaningful change should say so briefly rather than padding — a digest that always
  looks the same gets filtered.

#### Out of scope
- Per-recipient personalised digest content within one organization.
- Non-email delivery channels.
