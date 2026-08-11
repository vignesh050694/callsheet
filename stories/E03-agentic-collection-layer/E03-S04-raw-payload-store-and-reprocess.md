### User Story E03-S04:

- **Summary:** Reprocess the whole corpus with a better model without paying to collect it again

**Epic:** E03 — Agentic Collection Layer
**Phase:** 1
**Source:** Concept note §5.2 ("raw payloads stored verbatim for reprocessing without re-paying"), §7

#### Use Case:
- **As an** internal data ops engineer improving the analysis pipeline mid-pilot
- **I want to** re-run language ID, classification, and sentiment over stored raw payloads
- **so that** we can fix a pipeline mistake or upgrade a model across a title's full history without
  spending collection budget a second time

#### Acceptance Criteria:
- **Scenario:** Pipeline is re-run over an existing corpus after a model change
- **Given:** a title has six weeks of collected mentions
- **and Given:** every collection response was stored verbatim, including author, follower count,
  timestamp, engagement counts, hashtag entities, and media objects
- **and Given:** derived fields (language, account type, sentiment, themes) are stored separately
  from the raw payload and are versioned by pipeline version
- **and Given:** a reprocess job can target a title and a date range
- **When:** I trigger a reprocess of that title with the new pipeline version
- **Then:** all derived fields are recomputed from stored payloads with zero collection spend, and
  the dashboard reflects the new results with its pipeline version recorded

#### Notes
- This is the single most important architectural constraint in the concept note: analysis cost is
  the budget risk ($90–$900 per title), and being unable to reprocess would multiply it.
- Also the enabling mechanism for E02-S04 (re-matching on newly approved aliases) and E02-S05
  (undoing an exclusion).

#### Out of scope
- Re-fetching engagement counts as they change over time (a snapshot-at-collection model in v1).
- Long-term archival tiering of raw payloads.
