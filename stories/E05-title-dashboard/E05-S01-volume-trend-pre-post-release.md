### User Story E05-S01:

- **Summary:** See conversation volume as a trend split at release day

**Epic:** E05 — Title Dashboard
**Phase:** 1
**Source:** Concept note §5.4 ("pre-release vs post-release is first-class"), §9

#### Use Case:
- **As a** production house marketing head the morning after release
- **I want to** see how much people are talking about my title over time, with release day marked
- **so that** I can tell at a glance whether the film built on its pre-release buzz or dropped off
  the moment it was out

#### Acceptance Criteria:
- **Scenario:** Owner opens the dashboard the day after release
- **Given:** my title has been collecting since before release and has a recorded release date
- **and Given:** the Overview shows mention volume as a time series with a selectable date range
- **and Given:** the release date is drawn as a divider and campaign milestones as markers
- **and Given:** the chart states the account-type filter currently applied
- **When:** I open the Title Dashboard
- **Then:** I see the volume trend with pre-release and post-release visually separated and the
  totals for each period stated

#### Notes
- Volume must be normalised against polling cadence, or the automatic step up to surge cadence
  (E03-S02) will read as an audience spike.
- Media-only posts are included here — they count as conversation even though they are excluded
  from sentiment (E04-S06).

#### Out of scope
- Forecasting or projected volume.
- Benchmarking against other titles (Phase 4).
