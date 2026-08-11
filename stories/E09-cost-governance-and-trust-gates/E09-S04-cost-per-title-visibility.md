### User Story E09-S04:

- **Summary:** See what each title actually costs us, against what we projected

**Epic:** E09 — Cost Governance & Trust Gates
**Phase:** 1
**Source:** Concept note §7 (~$273/title collection, $90–$900 analysis), §9 gate, §10

#### Use Case:
- **As a** product owner deciding how to price this product
- **I want to** see collection and analysis cost per title per day against the modelled projection
- **so that** I can tell whether the $273 collection figure and the analysis range hold in reality
  before we commit to a price list

#### Acceptance Criteria:
- **Scenario:** Product owner reviews a pilot title's costs against the model
- **Given:** a pilot title has been collecting and analysing for several weeks
- **and Given:** every paid call and every analysis batch is recorded with its cost, platform, and
  cadence phase
- **and Given:** an internal cost view shows cost per title per day split into collection and
  analysis, against the §7 projection
- **and Given:** analysis cost is attributable to model and language
- **When:** I open the cost view for that title
- **Then:** I see actual versus projected cost per day with the variance called out, and can see
  which platform or which language is responsible for any overrun

#### Notes
- Attribution by language is what turns "analysis might cost $90 or $900" into an actionable
  decision, because the code-mixed subset is where the model ladder gets expensive.
- This view is also the evidence base for the §9 collection-cost gate and for the tier bands in
  E09-S05.
- Internal-only in v1; customers see usage against their tier, not our provider costs.

#### Out of scope
- Customer-facing cost transparency.
- Provider invoice reconciliation.
