# Stage prompt templates

Substitute the bracketed values. Every template starts the agent from the **story file**, not from
the previous stage's summary — that independence is what makes the review meaningful.

All four stages share these standing rules; repeat them in each prompt:

- Do not run `git commit`, `git checkout`, `git branch`, or `git push`. The orchestrator commits.
- Do not edit files under `stories/` — the story is a contract, not a work surface.
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

Read <STORY_PATH> first. Each Gherkin scenario in its Acceptance Criteria must map to at least
one test, named so the mapping is obvious. Then read the implementation at <CHANGED_FILES> to
learn the seams you are testing against — not to learn what behaviour to expect. Expected
behaviour comes from the story.

Also cover, beyond the happy path: the boundary conditions the story implies (the "form blocks
submission" style rules), the error paths, and any empty/absent-data case.

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
```

## Stage 4 — Document (Haiku)

`Agent(subagent_type: "general-purpose", model: "haiku", description: "document <STORY_ID>")`

```
Update the documentation for completed user story <STORY_ID>.

Read <STORY_PATH> for what the feature does and <CHANGED_FILES> for what was actually built.

Update only what this story changed:
- callsheet/README.md — new endpoints, env vars, setup or migration steps, make targets.
- callsheet-ui/README.md — new screens, routes, or scripts.
- Docstrings or module headers on the new public functions and classes, if the surrounding code
  uses them.
- A CHANGELOG entry if the project keeps one. Do not create one if it does not.

Rules:
- Do not modify implementation code, tests, or anything under stories/.
- Do not write documentation for behaviour that does not exist yet.
- Match the voice and structure of the existing docs. Short, factual, no marketing tone.
- If nothing needs documenting, change nothing and say so — that is a valid outcome.

Report: files changed with a one-line summary each, or "no documentation changes needed".
```
