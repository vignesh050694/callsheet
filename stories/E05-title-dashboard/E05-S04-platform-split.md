### User Story E05-S04:

- **Summary:** Compare how each platform is behaving, so I know where to spend next

**Epic:** E05 — Title Dashboard
**Phase:** 1
**Source:** Concept note §9 (MVP: platform split), §5.2

#### Use Case:
- **As a** production house marketing head planning the next burst of spend
- **I want to** see volume and sentiment broken down by platform
- **so that** I can put budget where my audience is actually talking rather than spreading it evenly
  across every channel

#### Acceptance Criteria:
- **Scenario:** Owner compares platforms during release week
- **Given:** my title collects from X, Reddit, YouTube, and Instagram
- **and Given:** the Overview has a platform split showing each platform's share of volume and its
  own sentiment reading
- **and Given:** the split respects the active account-type filter
- **and Given:** platforms that are stale or not configured are shown as such rather than as zero
- **When:** I view the platform split for release week
- **Then:** I see each platform's volume share and sentiment side by side, with any platform whose
  collection is incomplete clearly marked so I do not read a gap as silence

#### Notes
- The stale-vs-zero distinction is the same rule as E03-S05, applied to this view. A platform
  reading zero because collection broke and one reading zero because nobody posted must never
  look identical.
- Instagram is conditional in Phase 1 (pending §T6 post-level data), so this view must render
  correctly with three platforms.

#### Out of scope
- Per-platform cadence controls (E03-S02 keeps cadence global).
- Follower/reach modelling beyond what the platform returns.
