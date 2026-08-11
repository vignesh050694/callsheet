### User Story E09-S02:

- **Summary:** Make an uncapped PER_RESULT call impossible, not merely discouraged

**Epic:** E09 — Cost Governance & Trust Gates
**Phase:** 1
**Source:** Concept note §7 cost-control rule 3 (Apify Reddit scraper at $0.0057/result + $0.02 flat)

#### Use Case:
- **As an** internal data ops engineer
- **I want to** have the system refuse to execute a PER_RESULT call that carries no hard result cap
- **so that** one popular title on one busy day cannot turn a per-result endpoint into an unbounded bill

#### Acceptance Criteria:
- **Scenario:** A PER_RESULT endpoint is invoked without a result cap
- **Given:** an endpoint's inspected price model is PER_RESULT
- **and Given:** every PER_RESULT endpoint must carry a configured maximum result count
- **and Given:** the cap is enforced in the calling layer, independently of anything the provider does
- **and Given:** the projected worst-case cost is computed as cap × unit price plus any flat fee
- **When:** a run attempts to call that endpoint with no cap set, or with a cap whose worst-case cost
  exceeds the title's remaining budget
- **Then:** the call is rejected before execution and the rejection is logged with the projected
  worst-case cost that was avoided

#### Notes
- The named runaway risk is the Apify Reddit scraper at $0.0057/result plus a $0.02 flat fee; the
  YouTube Apify scraper at $0.00225 PER_RESULT sits in the same category.
- Rule 2 stands alongside this one: prefer PER_CALL endpoints, where cost is driven by pagination
  depth rather than by how popular the title happens to be that day.
- Server-side result caps on PER_RESULT endpoints are an open item with Monid (§11.6) — until they
  exist, this client-side cap is the only protection.

#### Out of scope
- Removing PER_RESULT endpoints entirely (some platforms have no PER_CALL equivalent).
