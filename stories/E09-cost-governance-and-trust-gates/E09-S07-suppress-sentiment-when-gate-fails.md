### User Story E09-S07:

- **Summary:** Show no sentiment at all rather than a sentiment we can't stand behind

**Epic:** E09 — Cost Governance & Trust Gates
**Phase:** 1
**Source:** Concept note §9 ("If the sentiment gate fails: ship without a sentiment number")

#### Use Case:
- **As a** product owner responsible for whether a production house trusts this product
- **I want to** switch sentiment off entirely for a language or a title that has not cleared its
  accuracy gate
- **so that** we never put a number in front of a customer that we cannot defend, since that loss of
  trust is permanent and not recoverable

#### Acceptance Criteria:
- **Scenario:** The code-mixed subset fails its gate while English passes
- **Given:** the evaluation in E09-S06 reports sentiment agreement below 0.75 for code-mixed Tamil
- **and Given:** sentiment display is controlled by a per-language, per-title suppression switch
- **and Given:** suppression removes sentiment from dashboards, exports, digests, and alerts
  consistently
- **and Given:** the remaining product — volume, themes, account-type split, spikes — stands on its
  own without gaps where sentiment used to be
- **When:** I suppress sentiment for the code-mixed subset on a Tamil-market title
- **Then:** no sentiment figure appears anywhere for that title, the coverage panel states plainly
  that sentiment is not reported for this language pending accuracy validation, and no
  sentiment-shift alerts are sent

#### Notes
- This story is the concept note's most important product decision made operational. Building it
  late means someone will be tempted to ship an ungated number instead.
- The fallback product must genuinely stand alone: E05-S01 (volume), E05-S07 (themes), E05-S03
  (account-type split), E04-S05 (spikes) are all designed to be sentiment-independent for this reason.
- Saying "not reported pending validation" is a stronger trust signal than a hedged score. It is
  also the honest description of the state we are in.

#### Out of scope
- Partial sentiment display with confidence caveats as an alternative to suppression — explicitly
  rejected; the concept note's instruction is to ship without the number.
