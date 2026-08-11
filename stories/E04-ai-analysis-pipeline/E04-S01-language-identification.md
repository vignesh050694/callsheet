### User Story E04-S01:

- **Summary:** Detect the language from the text itself, because the platform's tag is wrong half the time

**Epic:** E04 — AI Analysis Pipeline
**Phase:** 1
**Source:** Concept note §6.2 (NEW, mandatory — mislabelling table)

#### Use Case:
- **As a** production house owner tracking a Tamil release whose audience posts in Tamil written in
  Latin script
- **I want to** have each mention's real language determined from its content
- **so that** my regional-language audience is understood rather than silently misread as English,
  Indonesian, or Finnish

#### Acceptance Criteria:
- **Scenario:** A Tamil-in-Latin-script post carrying a wrong platform language tag is analysed
- **Given:** a collected post is written in Tamil using Latin script
- **and Given:** the platform has tagged that post `fi` (Finnish)
- **and Given:** the pipeline runs a language-identification step after entity match and before
  sentiment
- **and Given:** the step reads the post text and ignores the platform-supplied tag
- **and Given:** the step can return a code-mixed result rather than being forced to pick one language
- **When:** the post passes through language identification
- **Then:** the mention is stored with a detected language of Tamil (Latin script, code-mixed) and a
  confidence score, and the platform's `fi` tag is retained only as a diagnostic field

#### Notes
- Observed mislabelling in the live sample: Telugu-in-Latin-script (536K views) tagged `en`;
  Tamil tagged `in`; a Tamil film post tagged `ht`; a Tamil FDFS review tagged `fi`. Roughly half
  the non-English content was wrong.
- Keeping the platform tag lets us measure disagreement rate — a useful ongoing quality signal and
  a good sales anecdote.
- Low-confidence detections must be routable to a fallback rather than defaulting to English.

#### Out of scope
- Translation of mentions into English (not required for sentiment routing).
- Script transliteration/normalisation as a user-facing feature.
