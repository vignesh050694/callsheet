### User Story E04-S05:

- **Summary:** Detect volume spikes and say whether my own campaign caused them

**Epic:** E04 — AI Analysis Pipeline
**Phase:** 1
**Source:** Concept note §5.3, §5.5, §9 (spike markers against campaign dates)

#### Use Case:
- **As a** production house owner running a paid campaign alongside an organic release
- **I want to** have unusual jumps in conversation detected and attributed against my campaign
  milestones and account types
- **so that** I can tell an audience reaction apart from the noise my own trailer drop created

#### Acceptance Criteria:
- **Scenario:** Volume jumps sharply the day a trailer drops
- **Given:** my title has a baseline of daily volume and a recorded set of campaign milestones
- **and Given:** spike detection compares current volume against a rolling baseline per platform
- **and Given:** each detected spike records its magnitude, dominant account type, dominant theme,
  and nearest campaign milestone
- **and Given:** a spike driven by owned and promotional accounts is distinguishable from one driven
  by organic accounts
- **When:** volume jumps on the day of my trailer launch
- **Then:** a spike is recorded and marked as coinciding with the trailer milestone, with its
  organic share stated so I can see how much of it was audience rather than campaign

#### Notes
- Attribution here is co-occurrence, not causation — the UI wording must not overclaim.
- Baselines must be established before surge cadence begins; a spike detector that treats the
  cadence change itself as a volume spike is a known trap (normalise by polls, not raw counts).

#### Out of scope
- Predictive/forecast alerts ("this will trend tomorrow").
- Cross-title comparative spikes (Phase 4).
