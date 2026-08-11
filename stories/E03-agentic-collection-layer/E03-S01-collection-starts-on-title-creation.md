### User Story E03-S01:

- **Summary:** Get a populated dashboard within a day of creating a title, with no setup call required

**Epic:** E03 — Agentic Collection Layer
**Phase:** 1
**Source:** Concept note §5.2, §10 (time-to-first-insight < 24h target)

#### Use Case:
- **As a** production house owner who has just finished setting up my title
- **I want to** have collection begin on its own straight away
- **so that** I see real mentions on my dashboard the same day instead of waiting for someone to
  provision a job for me

#### Acceptance Criteria:
- **Scenario:** First collection run fires immediately after title setup completes
- **Given:** I have saved a title with a valid identity set and a release date
- **and Given:** my organization is within its spend controls
- **and Given:** the title has no prior collection history
- **and Given:** the dashboard shows a "Collecting your first mentions" state until data lands
- **When:** I complete title setup
- **Then:** a first collection run is queued within one minute and the Title Dashboard shows real
  mentions in under 24 hours without any manual intervention

#### Notes
- The first run is the one that seeds alias discovery (E02-S04), so it should span all configured
  query variants rather than a single cheap probe.
- Observed per-call latency is ~3.9s, so a full first poll across four platforms is a
  minutes-scale job, not a day-scale one — the 24h target has generous headroom.

#### Out of scope
- Historical backfill (E03-S03) — this story covers forward collection only.
- Cadence changes over the campaign (E03-S02).
