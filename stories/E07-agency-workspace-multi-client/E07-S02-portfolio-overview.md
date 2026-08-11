### User Story E07-S02:

- **Summary:** See every client's health on one screen so I know where to spend my Monday

**Epic:** E07 — Agency Workspace & Multi-Client Reporting
**Phase:** 3
**Source:** Concept note §4 P3, §10 (weekly active entities)

#### Use Case:
- **As an** agency account director responsible for a portfolio of clients
- **I want to** see one screen showing each client entity's volume, organic sentiment direction,
  and open alerts
- **so that** I can spot the client who needs attention this morning instead of opening six
  dashboards to find out

#### Acceptance Criteria:
- **Scenario:** Account director triages the portfolio at the start of the week
- **Given:** my agency has active grants on eight entities across six clients
- **and Given:** the portfolio view lists every entity I have access to with its volume for the
  period, its organic sentiment direction, and its unacknowledged alert count
- **and Given:** every figure uses the organic-audience default
- **and Given:** entities with stale collection are flagged rather than shown as quiet
- **When:** I open the portfolio view for the last seven days
- **Then:** I see each entity's state side by side and can open any one of them directly, with
  clients kept visually distinct so no row is misread as belonging to another client

#### Notes
- This is a list of independently-scoped rows, not a merged dataset — no cross-client aggregate
  totals, because those would be meaningless to any single client and risky to expose.
- The stale-vs-quiet distinction (E03-S05) matters most here, where a director is triaging by
  glancing at numbers.

#### Out of scope
- Ranking or benchmarking clients against each other.
- Portfolio-level exports mixing multiple clients into one file.
