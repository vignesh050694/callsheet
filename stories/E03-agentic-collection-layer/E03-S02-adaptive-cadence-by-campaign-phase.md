### User Story E03-S02:

- **Summary:** Poll harder during release week and back off when it's quiet, without me managing it

**Epic:** E03 — Agentic Collection Layer
**Phase:** 1
**Source:** Concept note §5.2 (adaptive cadence), §7 (dormant 2/day, campaign 12/day, surge 48/day)

#### Use Case:
- **As a** production house owner tracking a title from announcement to release
- **I want to** have the system poll more often as my release approaches and less often when
  nothing is happening
- **so that** I get near-live numbers on opening weekend without paying release-week rates for the
  eight quiet months before it

#### Acceptance Criteria:
- **Scenario:** A title crosses into release week and the cadence escalates on its own
- **Given:** my title has a release date recorded and is currently in the campaign phase at 12
  polls per day
- **and Given:** the cadence policy defines dormant (2/day), campaign (12/day), and release surge
  (48/day) phases
- **and Given:** the surge window is derived from the release date
- **and Given:** the Title Dashboard displays the current phase and its polling frequency
- **When:** the title enters its release-surge window
- **Then:** polling steps up to the surge rate automatically and the dashboard shows the phase
  change, with no action required from me

#### Notes
- Builds on the scheduler E03-S01 delivers; this story replaces its single default rate with a
  phase-driven one and adds the phase indicator to the dashboard.
- Phase transitions must also be triggerable by observed volume, not only by calendar — an
  unplanned controversy in the dormant phase should escalate cadence.
- Cadence changes are the primary lever on the ~$273/title collection model; any change to the
  policy must be reflected in the cost projection shown in E09-S04.
- Surge cadence is where overlapping polls stop being theoretical — confirm E03-S01's handling of
  the concurrent double-poll rollback still holds at 48/day.

#### Out of scope
- Per-platform independent cadences (v1 polls all configured platforms together).
- Customer-editable cadence (surface it as a tier property in E09-S05 instead).
- Staleness detection when a platform misses its expected interval (E03-S05).
