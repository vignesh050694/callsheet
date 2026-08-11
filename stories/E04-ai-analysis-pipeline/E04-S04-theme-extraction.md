### User Story E04-S04:

- **Summary:** Surface what the conversation is about, so a sentiment dip comes with a reason

**Epic:** E04 — AI Analysis Pipeline
**Phase:** 1
**Source:** Concept note §5.3, §9 (themes ship even if the sentiment gate fails)

#### Use Case:
- **As a** production house owner watching my film's reception
- **I want to** see the recurring subjects in the conversation — the music, a performance, the
  runtime, the climax — with their volume and direction
- **so that** I can act on *why* the audience is reacting instead of staring at a single score

#### Acceptance Criteria:
- **Scenario:** Themes are extracted from a release-week corpus
- **Given:** my title has a classified, language-tagged corpus for release week
- **and Given:** theme extraction runs after sentiment and before aggregation
- **and Given:** themes are derived from the corpus rather than from a fixed taxonomy
- **and Given:** each theme carries its mention count, its account-type breakdown, and example posts
- **When:** the pipeline processes release week
- **Then:** the title has a ranked list of themes for that period, each traceable to the mentions
  that produced it

#### Notes
- Themes must work independently of sentiment. Concept note §9 is explicit that if the sentiment
  gate fails we launch on "volume, themes, account-type split, and spikes" — so themes cannot be
  built as a decoration on top of a sentiment score.
- Themes should be comparable across time periods so a theme's rise or fall is visible.

#### Out of scope
- Cross-title theme benchmarking (Phase 4).
- Manual theme taxonomy authoring by customers.
