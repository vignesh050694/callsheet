### User Story E04-S06:

- **Summary:** Count image and video posts in volume, keep them out of sentiment, and admit it

**Epic:** E04 — AI Analysis Pipeline
**Phase:** 1
**Source:** Concept note §6.4 (known limitation to state honestly), §8 risk #9

#### Use Case:
- **As a** production house owner whose biggest-engagement posts are reaction videos with two words
  of caption
- **I want to** have those posts counted in volume but excluded from the sentiment calculation, and
  labelled as such
- **so that** my sentiment score is honest about what it did and did not read, instead of scoring
  "🔥🔥" as if it were a review

#### Acceptance Criteria:
- **Scenario:** A high-engagement video post with a two-word caption is processed
- **Given:** a collected post consists of a video plus a caption below the minimum text threshold
- **and Given:** the pipeline flags posts as media-only when their analysable text falls below that
  threshold
- **and Given:** media-only posts still carry entity match, account type, and engagement counts
- **and Given:** the aggregation layer keeps a media-only count per period
- **When:** the post is processed by the pipeline
- **Then:** it contributes to volume and engagement totals, is excluded from the sentiment
  denominator, and increments the period's declared sentiment coverage gap

#### Notes
- The coverage gap must be surfaced, not buried — E05-S08 is the UI half of this story.
- A large share of high-engagement posts fall in this bucket, so the gap number may be
  uncomfortable. Concept note §6.4 is explicit: label it rather than hide it.
- Emoji-only captions are a candidate exception worth testing before launch — a string of fire
  emoji does carry signal even when word count is zero.

#### Out of scope
- Any form of image or video understanding (Phase 4 at the earliest).
- OCR of text burned into posters and stills.
