### User Story E05-S08:

- **Summary:** Tell me what the sentiment score did not read, on the same screen as the score

**Epic:** E05 — Title Dashboard
**Phase:** 1
**Source:** Concept note §6.4 ("label the coverage gap in the UI rather than hiding it"), §8 risks #4, #9

#### Use Case:
- **As a** production house owner about to repeat a number to my head of studio
- **I want to** see what share of mentions the sentiment score actually covered, and why the rest
  were excluded
- **so that** I can state the number with its limits instead of being caught out later by a
  journalist or a rival agency

#### Acceptance Criteria:
- **Scenario:** Owner checks coverage before quoting a sentiment figure
- **Given:** my title's corpus contains media-only posts and low-confidence language detections
- **and Given:** the dashboard has a coverage panel adjacent to the sentiment chart
- **and Given:** the panel states the share of mentions scored, the share excluded as media-only,
  and the share excluded for low language confidence
- **and Given:** the panel breaks scored coverage down by detected language
- **When:** I open the coverage panel for the period I am about to quote
- **Then:** I see the scored share and each excluded share as explicit percentages, so I know
  exactly what the sentiment number is a number about

#### Notes
- This is the most counter-intuitive story in the epic and the most important for trust. The
  concept note is unambiguous: "Putting an inaccurate sentiment score in front of a production
  house destroys trust permanently and is not recoverable."
- The same panel is where per-language agreement scores are surfaced once measured (E09-S06),
  including the separately-reported code-mixed subset.
- Exports (E05-S09) must carry this disclosure with them.

#### Out of scope
- Closing the media-only gap (would require multimodal analysis, Phase 4+).
- Confidence intervals on the sentiment score itself.
