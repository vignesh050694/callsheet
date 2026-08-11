### User Story E04-S02:

- **Summary:** Score sentiment with a model that can actually read the language the post is in

**Epic:** E04 — AI Analysis Pipeline
**Phase:** 1
**Source:** Concept note §6 (revised pipeline), §7 (analysis cost ladder), §9 gate ≥ 0.75

#### Use Case:
- **As a** production house owner whose audience posts in Tamil, English, and a mix of both
- **I want to** have each mention scored by a model suited to its detected language
- **so that** the sentiment I read reflects what my audience said, not what an English-only model
  guessed at

#### Acceptance Criteria:
- **Scenario:** A batch containing English, Tamil-script, and code-mixed posts is scored
- **Given:** every mention in the batch carries a detected language and confidence from E04-S01
- **and Given:** the pipeline holds a routing table mapping language classes to sentiment models
- **and Given:** each mention's sentiment record stores the model and pipeline version that produced it
- **and Given:** mentions whose language confidence is below threshold are routed to the
  code-mixed-capable model rather than the English default
- **When:** the batch is scored
- **Then:** each mention receives a sentiment label from its routed model, and the code-mixed subset
  can be reported and evaluated separately from the English subset

#### Notes
- The routing table is the cost lever: cheap model for the languages it handles well, expensive
  model only where the gate demands it. Batched at 50 mentions per call, the spread between a
  small model and a frontier model over a major release is ~$90 vs ~$900.
- Separate reportability of the code-mixed subset is a hard requirement of the §9 gate, not a
  reporting nicety.

#### Out of scope
- The gate measurement itself (E09-S06) and the fail-safe if it is missed (E09-S07).
- Aspect-level sentiment (per-actor, per-song) — themes cover this in v1 (E04-S04).
