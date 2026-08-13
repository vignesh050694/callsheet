### User Story E02-S07:

- **Summary:** Judge title length the way a reader sees it so the anchor rule treats Indic titles consistently

**Epic:** E02 — Title Setup & Identity Discovery
**Phase:** 1
**Source:** E02-S01 review round 4 (follow-up); concept note §5.1, §6.1

#### Use Case:
- **As a** production house owner adding a short-named regional title
- **I want to** be asked for an anchor term whenever my title is short, whatever script I type it in
- **so that** two titles that look equally short to a reader are treated the same way, instead of
  one sailing through and the other being stopped

#### Acceptance Criteria:
- **Scenario:** Two Devanagari titles of the same perceived length are set up
- **Given:** "सीता" and "राधे" are each two aksharas — the same length to anyone reading them
- **and Given:** the anchor rule requires a term from the cast or crew for a short title name
- **When:** I submit each of them with no cast or crew term
- **Then:** both are refused with the same explanation, rather than one being created and the
  other refused

#### Notes
- Present in E02-S01 as shipped. `visible_length` in `app/core/identity_terms.py` counts code
  points, skipping categories `Mn` and `Me` but counting `Mc`. In Devanagari the common
  consonant-plus-spacing-vowel-sign syllable is `Lo`+`Mc`, so one akshara counts as two.
- Measured today: `सीता`, `गीता`, `काका`, `रामा` all count 4 and are accepted with no anchor
  term, while `राधे` counts 3 and `మజిలీ` counts 3 and both are refused. Same script, same
  perceived length, opposite outcomes.
- The fix is to count grapheme clusters: group each base character with its trailing combining
  marks (`Mn`, `Mc` and `Me` alike) and count the groups. That gives `राधे` 2, `మజిలీ` 3,
  `सीता` 2, `काका` 2 — consistent. Roughly ten lines, no new dependency.
- This is a behaviour change. Titles such as `सीता` that are accepted bare today would then
  require an anchor term. That is the intended reading of the rule, but it will change what
  existing setup flows accept, so it wants a deliberate decision rather than a silent fix.
- `callsheet-ui/src/lib/title-identity.ts` mirrors the same rule and must change with it.

#### Out of scope
- Invisible characters passing as anchor terms (E02-S06).
- Changing the four-character threshold itself, or replacing the length test with a different
  heuristic such as "always require an anchor" — either would be a product decision, not a
  correction.
