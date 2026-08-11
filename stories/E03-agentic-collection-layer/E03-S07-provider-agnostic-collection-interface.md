### User Story E03-S07:

- **Summary:** Swap a data provider behind a stable interface, so one vendor can't take the product down

**Epic:** E03 — Agentic Collection Layer
**Phase:** 1
**Source:** Concept note §8 risk #5 ("keep the agent's tool interface abstract"), §11.3, §11.6

#### Use Case:
- **As an** internal data ops engineer responsible for uptime
- **I want to** substitute the endpoint or provider behind a platform without touching the pipeline
  or the dashboards
- **so that** a single aggregator's outage or price change is a configuration change rather than a
  product outage

#### Acceptance Criteria:
- **Scenario:** An X search endpoint is deprecated and must be replaced
- **Given:** the collection agent calls platforms through an internal interface that speaks in
  platform + query + page, not in vendor endpoint paths
- **and Given:** each platform has a configured primary endpoint and an optional alternative
- **and Given:** every provider response is normalised into a single internal mention shape before
  storage
- **and Given:** raw vendor payloads are still stored verbatim alongside the normalised form
- **When:** I change the configured endpoint for X to the alternative provider
- **Then:** collection continues against the new endpoint with no change to pipeline code or
  dashboards, and mentions from both providers appear in one continuous trend

#### Notes
- Monid is a single point of dependency for the entire collection layer; this story is the whole
  mitigation for risk #5 and should not be deferred out of Phase 1.
- Provider substitution behaviour when an endpoint goes down is an open question with Monid
  (§11.6) — resolve before finalising the failover half of this story.

#### Out of scope
- Automatic mid-run failover (v1 is configuration-driven switchover).
- Building direct platform API integrations as a fallback.
