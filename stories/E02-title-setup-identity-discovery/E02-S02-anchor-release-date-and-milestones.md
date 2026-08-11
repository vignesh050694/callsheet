### User Story E02-S02:

- **Summary:** Anchor the title to its release date so every chart reads as before vs after

**Epic:** E02 — Title Setup & Identity Discovery
**Phase:** 1
**Source:** Concept note §5.4 ("pre-release vs post-release is first-class"), §5.1 (key campaign dates)

#### Use Case:
- **As a** production house marketing head planning a campaign
- **I want to** record the release date and my key campaign beats (teaser, trailer, audio launch,
  bookings open) on the title
- **so that** when I look at a volume spike I can immediately tell whether my own campaign caused it
  or the audience did

#### Acceptance Criteria:
- **Scenario:** Owner records the release date and campaign milestones during title setup
- **Given:** I am creating or editing a title
- **and Given:** the setup form has a required release date and an optional repeatable list of
  campaign milestones, each with a name and a date
- **and Given:** the release date is used as the pre-release / post-release boundary everywhere
- **and Given:** I can add milestones later without disturbing already-collected data
- **When:** I save the title with a release date and three campaign milestones
- **Then:** every time-series view for this title renders a release-date divider and a marker per
  milestone, and the dashboard exposes a pre-release / post-release toggle anchored to that date

#### Notes
- Changing the release date after collection has started re-renders the split without re-collecting
  or re-analysing anything — the boundary is a read-time property.
- Milestone dates are the reference points spike detection explains itself against (E04-S05).

#### Out of scope
- Importing campaign calendars from external tools.
- Territory-specific staggered release dates.
