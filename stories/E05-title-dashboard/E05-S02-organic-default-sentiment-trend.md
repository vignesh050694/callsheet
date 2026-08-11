### User Story E05-S02:

- **Summary:** See sentiment that means the public, not my own press, by default

**Epic:** E05 — Title Dashboard
**Phase:** 1
**Source:** Concept note §3, §6.3 ("the default view should be organic-only"), §9

#### Use Case:
- **As a** production house marketing head deciding whether to extend a paid campaign
- **I want to** see a sentiment trend that counts only organic audience accounts unless I say otherwise
- **so that** I am reading how the public feels rather than reading my own distributors' and
  trackers' enthusiasm back to myself

#### Acceptance Criteria:
- **Scenario:** Owner views the sentiment trend on the default dashboard load
- **Given:** my title's corpus contains organic, trade, owned, and promotional mentions
- **and Given:** the sentiment trend is scoped to organic audience mentions on first load, with the
  active scope labelled on the chart
- **and Given:** the chart states the number of mentions the score is computed from
- **and Given:** an "all account types" comparison is one click away
- **When:** I open the Title Dashboard without changing any filter
- **Then:** the sentiment trend I see is computed from organic audience mentions only, and switching
  to all account types visibly changes the line — making the contamination its own insight

#### Notes
- Showing the organic vs all-types delta is both a product feature and a sales argument: the
  organic-vs-total mention ratio is a tracked success metric (§10).
- If the sentiment gate fails (§9), this entire chart is suppressed per E09-S07 and the dashboard
  falls back to volume, themes, account-type split, and spikes.

#### Out of scope
- Per-language sentiment breakdown on the main chart (available in the coverage panel, E05-S08).
- Sentiment on media-only posts (E04-S06 — excluded by design).
