### User Story E09-S01:

- **Summary:** Confirm what a call costs before paying for it, on every single run

**Epic:** E09 — Cost Governance & Trust Gates
**Phase:** 1
**Source:** Concept note §7 cost-control rule 1 ("`monid_inspect` before every `monid_run`")

#### Use Case:
- **As an** internal data ops engineer responsible for spend
- **I want to** have the collection agent verify an endpoint's price model before it executes a
  paid call
- **so that** a silent provider price change or a swapped endpoint cannot quietly multiply our cost
  per title before anyone notices

#### Acceptance Criteria:
- **Scenario:** A provider changes an endpoint's price model between runs
- **Given:** the collection agent is about to execute a paid call against a configured endpoint
- **and Given:** the agent inspects the endpoint's price model and unit price first
- **and Given:** each endpoint has an expected price model and a ceiling price in configuration
- **and Given:** inspection results are cached only for a short, bounded window
- **When:** the inspected price model or unit price differs from what is configured
- **Then:** the run is halted before any paid call is made and an operational alert is raised naming
  the endpoint, the expected price, and the observed price

#### Notes
- Halting rather than proceeding-and-warning is deliberate: the entire cost model rests on
  $0.0015–$0.003 PER_CALL pricing, and a shift to PER_RESULT changes the economics of the product,
  not just the size of one bill.
- Rate limits per key at surge cadence are still an open question with Monid (§11.6); the
  inspect-then-run pattern should be built to tolerate throttling on the inspect call itself.

#### Out of scope
- Automatic migration to a cheaper equivalent endpoint (E03-S07 covers manual substitution).
- Negotiated commercial terms with providers.
