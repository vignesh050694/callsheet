### User Story E08-S03:

- **Summary:** Be told when audience opinion turns, and only when it's the audience turning

**Epic:** E08 — Alerts & Digests
**Phase:** 3
**Source:** Concept note §5.5 (sentiment-shift alert), §6.3, §9 (gate ≥ 0.75)

#### Use Case:
- **As a** production house marketing head whose film has just opened
- **I want to** be alerted when organic audience sentiment moves materially against its recent level
- **so that** I learn about a turn in reception early enough to change my messaging rather than
  after the weekend is lost

#### Acceptance Criteria:
- **Scenario:** Organic sentiment declines materially two days after release
- **Given:** my title's sentiment has cleared the §9 agreement gate for its dominant languages
- **and Given:** sentiment-shift detection runs on organic audience mentions only
- **and Given:** a shift must exceed both a magnitude threshold and a minimum mention count to fire
- **and Given:** the alert states which themes moved and in which languages
- **and Given:** no sentiment alerts are sent for a title whose sentiment is suppressed under E09-S07
- **When:** organic sentiment declines beyond the threshold on sufficient volume
- **Then:** I receive an alert naming the themes driving the decline, linking to those mentions

#### Notes
- Restricting to organic accounts is essential: a burst of promotional posts can move a blended
  sentiment average without any real change in audience opinion.
- The minimum-mention-count condition prevents a handful of posts in a low-volume window from
  firing a false alarm — a common failure in listening tools.
- This story does not ship at all if the sentiment gate fails. That is the intended behaviour, not
  a degradation to work around.

#### Out of scope
- Sentiment alerts on trade, owned, or promotional accounts.
- Cause attribution beyond theme and language correlation.
