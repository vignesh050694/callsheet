### User Story E08-S02:

- **Summary:** Know within the hour when the conversation about my title jumps

**Epic:** E08 — Alerts & Digests
**Phase:** 3
**Source:** Concept note §5.5 (spike alert), §6 (latency improved — 3.9s per call, surge cadence affordable)

#### Use Case:
- **As a** production house marketing head during a release window
- **I want to** be alerted when conversation about my title spikes well beyond its normal level
- **so that** I can respond to a moment while it is still happening rather than reading about it the
  next morning

#### Acceptance Criteria:
- **Scenario:** Organic conversation spikes unexpectedly outside a campaign beat
- **Given:** my title is in its release-surge cadence with an established baseline
- **and Given:** spike detection is running per E04-S05
- **and Given:** alerts fire only for spikes above my configured threshold
- **and Given:** the alert states magnitude, dominant account type, dominant theme, and whether it
  coincides with a campaign milestone
- **When:** organic volume rises sharply with no campaign milestone nearby
- **Then:** I receive an alert within one polling interval that names the likely driver and links
  straight to the mentions, so I can see whether it needs a response

#### Notes
- Stating the dominant account type in the alert itself is what stops a distributor's promo blast
  from waking a marketing head at midnight.
- Surge cadence (48 polls/day) sets the practical floor on alert latency at ~30 minutes; do not
  promise faster in the UI.
- One alert per ongoing spike, updated — not one per polling interval while it continues.

#### Out of scope
- Predicting spikes before they happen.
- Auto-responding or drafting replies (out of scope for v1).
