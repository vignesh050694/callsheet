### User Story E04-S07:

- **Summary:** Try a cheaper model on a stored corpus and compare before committing to it

**Epic:** E04 — AI Analysis Pipeline
**Phase:** 1
**Source:** Concept note §5.3 ("swappable behind an internal interface"), §7 (analysis cost is the risk)

#### Use Case:
- **As an** internal data ops engineer deciding how much model to buy per language
- **I want to** re-run analysis over the same stored corpus with a different model and compare the
  results side by side
- **so that** we can pick the cheapest model that still clears the accuracy gate, instead of paying
  frontier-tier prices across every language by default

#### Acceptance Criteria:
- **Scenario:** A cheaper model is evaluated against the current one on a labelled corpus
- **Given:** a title's raw payloads are stored and a human-labelled evaluation subset exists
- **and Given:** language ID, classification, sentiment, and theme extraction each sit behind an
  internal interface with the model named in configuration
- **and Given:** each derived record stores the model and pipeline version that produced it
- **and Given:** two pipeline versions' outputs can coexist for the same mentions
- **When:** I run the corpus through a second pipeline version using a cheaper sentiment model
- **Then:** I get a per-language comparison of agreement against the human labels and the measured
  cost per 1,000 mentions for each version, without any new collection spend

#### Notes
- This is the story that turns "$90 vs $900 per title" from a guess into a measurement, and it is
  what makes the sentiment gate a unit-economics gate rather than only a quality gate.
- Depends entirely on E03-S04 (raw payload store).
- Comparison must be per-language — the right answer is likely a cheap model for English and a
  stronger one for code-mixed Tamil.

#### Out of scope
- Automatic model selection or routing optimisation.
- Fine-tuning or training a bespoke model.
