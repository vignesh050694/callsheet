# Stage prompt templates

Substitute the bracketed values. Every template starts the agent from the **story file**, not from
the previous stage's summary — that independence is what makes the review meaningful.

All three stages share these standing rules; repeat them in each prompt:

- Do not run `git commit`, `git checkout`, `git branch`, or `git push`. The orchestrator commits.
- Do not edit files under `stories/` — the story is a contract, not a work surface.
- Do not write documentation. No README, CHANGELOG, or API-doc updates; this pipeline ships code,
  tests, and the ledger only.
- Report what you actually did. If something failed or you skipped it, say so plainly.

---

## Stage 1 — Implement (Opus)

Run inline if the session is already Opus (better context, no handoff loss). Otherwise:
`Agent(subagent_type: "general-purpose", model: "opus", description: "implement <STORY_ID>")`.

```
Implement user story <STORY_ID> in this repository.

Read first, in this order:
1. <STORY_PATH> — the acceptance criteria are the contract. Every Given/When/Then must hold.
2. <EPIC_PATH> — the epic hypothesis, its gate, and its dependencies bound the work.
3. The story's "Out of scope" section — do not build anything listed there.

Scope: implement exactly what the story's Use Case and Acceptance Criteria describe. Do not
generalise beyond them, do not add adjacent features, do not refactor unrelated code.

Standards that apply to this story:
- Backend (callsheet/): the backend-coding-standards and python-naming-conventions skills.
  Strict layering — routes route, services hold logic, repositories query. No function over
  100 lines. Log every request with response time.
- Frontend (callsheet-ui/): the social-intel-ui-standards skill. Check its four invariants
  (account-type segmentation, language provenance, human approval gates, sentiment colour
  budget) BEFORE building the screen, not after.
- Match the conventions of surrounding code — naming, comment density, error handling.

Do not write tests — a separate agent writes them against the same acceptance criteria. Your
implementation must be testable from outside: real seams, injectable dependencies, no logic
buried where a test cannot reach it.

<REVIEW_FEEDBACK — on a re-run, paste the reviewer's findings verbatim here and state that they
must all be addressed.>

Report: files created or modified with one line each on what changed, any acceptance criterion
you could not satisfy and why, and the exact command to exercise the feature.
```

## Stage 2 — Write tests (Sonnet)

`Agent(subagent_type: "general-purpose", model: "sonnet", description: "test <STORY_ID>")`

```
Write the test suite for user story <STORY_ID>. You did not write the implementation and you are
not here to defend it.

Read <STORY_PATH> first. Each Gherkin scenario in its Acceptance Criteria must map to **exactly
one** test, named so the mapping is obvious. Then read the implementation at <CHANGED_FILES> to
learn the seams you are testing against — not to learn what behaviour to expect. Expected
behaviour comes from the story.

BUDGET: the scenario tests, plus at most **five** more of your own choosing. Spend those five
where this story is most likely to be wrong — the boundary the story implies, the error path, the
empty-data case, the input that is text in a script or encoding the implementer probably did not
try. Five sharp tests beat fifty mechanical ones; a story with eight scenarios should land ~13
tests, not 90. If you believe a story genuinely needs more, write the five, then report what else
you would have covered and why — do not exceed the budget on your own.

Where to put them:
- Backend: callsheet/tests/, pytest, following the existing layout and fixtures. Run with
  `cd callsheet && uv run pytest -q`.
- Frontend: alongside the existing test setup in callsheet-ui/; if the project has no test
  runner configured, say so and stop rather than introducing one on your own.

HARD RULE: you may not modify implementation source to make a test pass. If a test fails because
the implementation is wrong, leave the test failing and report it — that is a finding, and it is
the most valuable thing you can return.

Report: the test files you wrote, the scenario-to-test mapping, the full output of the test run,
and every failure with your reading of whether the test or the implementation is at fault.
```

## Stage 3 — Review and verify (Sonnet, fresh agent)

`Agent(subagent_type: "general-purpose", model: "sonnet", description: "review <STORY_ID>")` —
must be a new agent, never a follow-up to Stage 2.

```
Review the implementation of user story <STORY_ID> and verify it. Be adversarial: your job is to
find what is wrong, not to confirm it looks fine.

1. Read <STORY_PATH> and <EPIC_PATH>.
2. Read the diff: `git diff main...HEAD` plus `git status --porcelain` for uncommitted work.
3. Run the verify command and paste its real output:
   - Backend touched: `cd callsheet && make check`
   - Frontend touched: `cd callsheet-ui && npm run check` (add `npm run build` if the build
     config or dependencies changed)

Check, and give a per-item verdict:
- Every Gherkin scenario in the story — satisfied by the code, or not. Name the line that
  satisfies it.
- Tests genuinely exercise the criteria rather than asserting the implementation back at itself
  (mocks that make the assertion vacuous, tests with no meaningful assertion, scenarios missing).
- Anything from the story's "Out of scope" that got built anyway.
- Backend: layering violations, functions over 100 lines, missing request logging, naming that
  breaks python-naming-conventions.
- Frontend: the four social-intel-ui-standards invariants.
- Correctness bugs in the diff: wrong boundaries, unhandled errors, state that can go stale,
  concurrency or ordering assumptions.

Return a verdict of exactly `pass` or `changes-requested`. `changes-requested` if any acceptance
criterion is unmet, any check fails, or you found a real bug. For each finding: file:line, what
is wrong, and the concrete failure it causes. No style preferences, no speculation — only what
you can point at.

Missing documentation is not a finding — this pipeline does not produce docs. Only flag a doc as
missing if the story's own acceptance criteria name it.
```

---

## Re-runs (review loop rounds 2 and 3)

A first review starts cold — that independence is what makes the verdict worth anything. A
*re-review* does not: rediscovering the whole story to check a two-line fix is most of the loop's
cost. Round 2 and 3 still use a **fresh agent**, but a briefed one.

**Stage 2 on a re-run** — do not rewrite the suite. Append this to the prompt:

```
Tests for this story already exist at <TEST_FILES>. The implementation changed to address these
reviewer findings:

<FINDINGS_VERBATIM>

Keep the existing tests. Add tests only for behaviour those findings changed, and update any
existing test whose expectation the fix legitimately invalidates — say which and why. The test
budget above does not reset; it applies to what you add this round.
```

**Stage 3 on a re-run** — replace steps 1–2 of the template with:

```
This is review round <N> for <STORY_ID>. Round <N-1> returned changes-requested with:

<FINDINGS_VERBATIM>

1. Read <STORY_PATH>. Skim <EPIC_PATH> only for the gate and out-of-scope list.
2. Read `git diff` since the previous round — that delta is your primary surface.
3. Verdict on each prior finding: fixed, not fixed, or fixed-but-introduced-something-else.
   A fix that trades one defect for another is `changes-requested`.
4. Then run the full check and re-read the whole diff for anything the earlier round missed.
   Prior rounds constrain where you look first, not what you are allowed to find.
```
