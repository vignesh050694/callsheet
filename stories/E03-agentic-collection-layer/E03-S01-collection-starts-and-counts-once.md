### User Story E03-S01:

- **Summary:** Get a populated dashboard within a day of creating a title, with each post counted
  once no matter how many queries found it

**Epic:** E03 — Agentic Collection Layer
**Phase:** 1
**Source:** Concept note §5.2, §6 (pipeline: ingest → dedupe → entity match),
§10 (time-to-first-insight < 24h target)

> **Absorbs the former E03-S06 (deduplicate mentions).** This story already requires the poll to
> span every configured query variant, which is the exact condition that makes deduplication
> load-bearing from the first poll onward. With the dedupe key (platform + native post ID) already
> built in E03-S07, what remained of S06 was a matched-variant list and the fan-out this story
> introduces — not a story on its own. Cadence is **not** here; it is E03-S02.

#### Use Case:
- **As a** production house owner who has just finished setting up my title and is tracked through
  five overlapping query variants
- **I want to** have collection begin on its own straight away, and the same post counted only once
  no matter how many of those queries returned it
- **so that** I see real mentions on my dashboard the same day instead of waiting for someone to
  provision a job for me, and my mention volume is a real measure of conversation rather than a
  measure of how many search terms I configured

#### Acceptance Criteria:

- **Scenario:** First collection run fires immediately after title setup completes
- **Given:** I have saved a title with a valid identity set and a release date
- **and Given:** my organization is within its spend controls
- **and Given:** the title has no prior collection history
- **and Given:** the dashboard shows a "Collecting your first mentions" state until data lands
- **When:** I complete title setup
- **Then:** a first collection run is queued within one minute and the Title Dashboard shows real
  mentions in under 24 hours without any manual intervention

- **Scenario:** The same post is returned by several query variants in one polling cycle
- **Given:** my title runs five query variants per platform per poll
- **and Given:** a single popular post matches three of those variants
- **and Given:** deduplication keys on platform plus native post ID
- **and Given:** the retained record preserves which query variants matched it
- **When:** the polling cycle completes and the pipeline runs
- **Then:** the post contributes exactly one mention to volume, sentiment, and every chart, while
  the matched-variant list is retained for alias-discovery analysis

#### Notes
- The first run is the one that seeds alias discovery (E02-S04), so it should span all configured
  query variants rather than a single cheap probe — which is also what makes deduplication
  load-bearing from the very first poll.
- Observed per-call latency is ~3.9s, so a full first poll across four platforms is a
  minutes-scale job, not a day-scale one — the 24h target has generous headroom.
- Recurring polling runs at a single default rate in this story. Phase-driven rates are E03-S02;
  this story must not hard-code the rate somewhere S03 cannot reach.
- E03-S07 left a known limit for this story: a page commits as one transaction, so a genuinely
  concurrent double-poll of the same title can hit the `mentions` unique constraint and roll back a
  whole page including its new items. It becomes reachable the moment this story's scheduler
  exists. (Recorded against E03-S02 before the scheduler moved here.)
- Verbatim reposts/retweets are a separate, deliberate decision: they are distinct posts by
  distinct authors and should be counted, but flagged as amplification so E05 can show
  "conversations vs amplifications".
- Near-duplicate promotional text posted by many cinema chains is handled by account-type
  classification (E04-S03), not by dedupe.

#### Out of scope
- Historical backfill (E03-S03) — this story covers forward collection only.
- Cadence changes over the campaign (E03-S02).
- Cross-platform identity resolution (the same person posting on X and Instagram).
- Semantic near-duplicate clustering.
