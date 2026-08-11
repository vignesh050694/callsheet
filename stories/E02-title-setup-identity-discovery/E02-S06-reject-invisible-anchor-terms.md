### User Story E02-S06:

- **Summary:** Reject invisible characters as anchor terms so the collectability rule cannot be waved through

**Epic:** E02 — Title Setup & Identity Discovery
**Phase:** 1
**Source:** E02-S01 review round 4 (follow-up); concept note §5.1, §6.1

#### Use Case:
- **As a** production house owner setting up a short-named title
- **I want to** be stopped when the cast name I entered is not really a name
- **so that** a title I believe is anchored is actually collectable, rather than quietly producing
  the bare-name query the setup form exists to prevent

#### Acceptance Criteria:
- **Scenario:** A term made only of an invisible character is offered as the anchor for a short title
- **Given:** the anchor rule requires a short title name to carry at least one cast or crew term
- **and Given:** a variation selector (U+FE00–U+FE0F) is Unicode category `Mn` and renders nothing
  on its own
- **and Given:** the title name is two characters, so it needs an anchor term to be collectable
- **When:** I submit that title with a variation selector as its only lead cast entry
- **Then:** the submission is refused with the same explanation any unanchored short name gets,
  and no title is created

#### Notes
- Present in E02-S01 as shipped. Reproduced: `POST /organizations/{id}/titles` with
  `{"name": "DC", "lead_cast": ["️"]}` returns 201 with `has_anchor_term: true`.
- `has_meaningful_content` in `app/core/identity_terms.py` treats only categories
  `Cc/Cf/Zl/Zp/Zs` plus an explicit blank-rendering set as invisible. Category `Mn` is not
  covered, and variation selectors live there.
- The client mirror in `callsheet-ui/src/lib/title-identity.ts` has the same gap, so the form's
  submit button is enabled too — this is not a client/server disagreement, it is one rule wrong
  in both places. Fix them together.
- Six earlier bypasses of this rule were each a different Unicode neighbour. Prefer a fix that
  asks "does this render anything" rather than one that adds `Mn` to a category list.

#### Out of scope
- The grapheme-counting inconsistency in the same rule (E02-S07).
- Judging whether a visible term is a plausible human name — punctuation such as `...` is
  accepted as an anchor by design.
