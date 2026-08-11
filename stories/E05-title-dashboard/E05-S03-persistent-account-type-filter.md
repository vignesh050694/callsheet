### User Story E05-S03:

- **Summary:** Switch the whole dashboard between audience, trade, owned, and promo in one control

**Epic:** E05 — Title Dashboard
**Phase:** 1
**Source:** Concept note §6.3 ("every dashboard number must be filterable by it"), §11.5

#### Use Case:
- **As a** production house marketing head reviewing release week
- **I want to** switch every number on the dashboard between account types with a single persistent
  control
- **so that** I can answer "what does the public think?" and "what is the trade saying?" as two
  separate questions without rebuilding my filters on every screen

#### Acceptance Criteria:
- **Scenario:** Owner switches to trade accounts and moves between dashboard screens
- **Given:** the dashboard has a persistent account-type control in its header offering organic
  audience, trade / tracker, owned media, and promotional
- **and Given:** the control defaults to organic audience
- **and Given:** every volume, sentiment, theme, platform, and feed view respects the control
- **and Given:** the selection survives navigation between Overview and Mentions Feed
- **When:** I switch the control to trade / tracker and open the Mentions Feed
- **Then:** every figure and the feed itself are scoped to trade accounts, with the active scope
  labelled on each chart so no screenshot can be read out of context

#### Notes
- §11.5 makes this a persistent control on Overview and Mentions Feed specifically — not a
  per-chart dropdown. Screenshots of this dashboard will circulate inside studios; every chart
  must carry its own scope label for that reason.
- Exports (E05-S09) must carry the active scope in the file and its filename.

#### Out of scope
- Multi-select combinations beyond "one type" and "all types" in v1.
- Editing an individual account's classification from the filter (correction flow is E09-S06).
