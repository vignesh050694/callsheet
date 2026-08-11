---
name: story-delivery
description: Deliver a user story or a whole epic from the `stories/` backlog through a fixed three-model pipeline — Opus implements, Sonnet writes the tests, Sonnet reviews and runs them — on a per-epic git branch with one commit per story and status tracked in that epic's EPIC.md. Use whenever the request names a story or epic ID (E02-S01, "epic E03", "next story in E05"), or says implement/build/deliver/pick up a backlog story, "start the next story", "work through this epic", or asks for story or epic status. Trigger even when the request sounds like plain coding work — "add the title setup form", "build the language ID service" — if the work maps to a story file under stories/.
---

# Story Delivery Pipeline

Delivers backlog stories under `stories/` through a fixed assembly line. The behaviour this enforces:
**every story is implemented by Opus, tested by a separate Sonnet, reviewed and verified by another
separate Sonnet, and lands as exactly one commit on its epic's branch — and the epic's `EPIC.md` is
the ledger that says where every story stands.**

This pipeline does not produce documentation. No README, CHANGELOG, or API-doc stage — code, tests,
and the `EPIC.md` ledger are the whole deliverable. If a story's own acceptance criteria call for a
doc, the implementer writes it as part of Stage 1; otherwise nothing is documented.

The separation is the point. The agent that writes the code does not write its own tests, and neither
of them signs off on the result. Each stage starts from the story's acceptance criteria, not from the
previous agent's summary.

## The pipeline

| Stage | Model | Runs as | Produces |
|---|---|---|---|
| 1. Implement | **Opus** | inline (or `Agent(model: "opus")`) | working code |
| 2. Test | **Sonnet** | `Agent(model: "sonnet")` | tests covering every Gherkin scenario |
| 3. Review & verify | **Sonnet** | `Agent(model: "sonnet")`, fresh | verdict + failing-test output |
| 4. Commit & track | — | orchestrator only | one commit + `EPIC.md` status row |

Stage 3 must be a **new** agent, not a follow-up message to the stage-2 agent — a reviewer that wrote
the tests will defend them.

Only the orchestrator (you) runs `git commit`. Subagents write files and report; they never commit,
never branch, never push.

## Repository facts this pipeline runs against

- Backend `callsheet/` — Python, FastAPI, uv, pytest. Verify with `cd callsheet && make check`
  (`ruff check` + `mypy app` + `pytest -q`). Tests live in `callsheet/tests/`.
- Frontend `callsheet-ui/` — React + Vite + TypeScript. Verify with `cd callsheet-ui && npm run check`
  (`oxlint` + `tsc -b --noEmit` + `prettier --check`), and `npm run build` for anything touching the
  build.
- Backlog `stories/E0N-<slug>/` — one `EPIC.md` plus one `E0N-SMM-<slug>.md` per story.

Backend work also carries `backend-coding-standards` and `python-naming-conventions`; any user-facing
screen carries `social-intel-ui-standards`. Pass those obligations into the implementer's prompt —
Stage 3 checks them.

## Step 0 — Preflight (before any agent starts)

1. **Resolve the target.** Map the request to a story file. `E05-S03` →
   `stories/E05-title-dashboard/E05-S03-*.md`. If the request names an epic, take the first story
   whose status is not `done`, in the order listed in `EPIC.md`.
2. **Read the story file in full, and its `EPIC.md`.** The Gherkin scenarios are the contract for
   Stages 1–3. The epic's *gate* and *out of scope* section bound them.
3. **Check dependencies.** If `EPIC.md` lists a blocking epic whose stories are not `done`, or the
   story's Notes name a prerequisite story that is not `done`, stop and tell the user which one —
   do not build around a missing dependency.
4. **Check the tree is clean.** `git status --porcelain`. Uncommitted work belonging to someone else
   means stop and ask; the pipeline assumes it owns the working tree.
5. **State the plan** in two or three lines before starting: story ID, epic branch, what the three
   stages will each cover. Then run it without further check-ins unless something blocks.

## Step 1 — Epic branch

One branch per epic, named `epic/<epic-folder-name>`:

```bash
git rev-parse --verify epic/E02-title-setup-identity-discovery 2>/dev/null \
  || git checkout -b epic/E02-title-setup-identity-discovery main
git checkout epic/E02-title-setup-identity-discovery
```

Every story in that epic commits onto the same branch. Never commit story work to `main`. Do not
push, open a PR, or merge unless the user asks — see *Finishing an epic*.

## Step 2 — Stages 1 through 3

Run them in order. The prompt template for each stage is in `references/agent-prompts.md` — use it;
the templates carry the constraints that keep the stages honest (Stage 2 may not modify source to
make a test pass; Stage 3 must be adversarial).

**The review loop.** If Stage 3 returns `changes-requested`, go back to Stage 1 with the reviewer's
findings and re-run Stages 2–3. Cap at **two** loops. On a third failure, stop, leave the work
uncommitted, set the story's status to `blocked` with the reason, and hand the reviewer's output to
the user.

**Never** relax an acceptance criterion, delete a failing test, or narrow a scenario to get green.
If a criterion is genuinely wrong or unimplementable, stop and say so — amending the story is the
user's call.

## Step 3 — Commit

One commit per story, containing implementation, tests, and the `EPIC.md` status update together.
Format and the required trailers are in `references/commit-and-status.md`.

Commit only after Stage 3 returns `pass` and the verify command is green. Report the actual result —
if a pre-existing unrelated failure is in the way, say so explicitly rather than describing the run
as passing.

## Step 4 — Track status in EPIC.md

`EPIC.md` is the single source of truth for story status. Story files are the contract and stay
unedited by this pipeline.

Statuses: `todo` · `in-progress` · `in-review` · `done` · `blocked`.

Update the epic's Stories table (adding the `Status` and `Commit` columns on first run if the table
predates this skill), and append a Delivery Log line. Exact table shape, wording, and the epic-level
rollup are in `references/commit-and-status.md`.

Set `in-progress` when Stage 1 starts and `in-review` when Stage 3 starts, so an interrupted run
leaves a truthful ledger. The move to `done` happens in the story's own commit.

## Working through a whole epic

When asked for an epic rather than a story: run the full pipeline story by story, in the order
`EPIC.md` lists them, committing each before starting the next. Report a one-line result per story as
you go. Stop the run and surface it if a story ends `blocked` — later stories in an epic usually
build on earlier ones.

## Finishing an epic

When every story in an epic is `done`:

1. Run the full verify command for each affected project one more time on the epic branch.
2. Update the epic rollup in `EPIC.md`, and the `stories/README.md` epic table if it tracks status.
3. Report the branch name, the story commits on it, and whether the epic's *gate* was measured or is
   still outstanding — a gate is measured by a story (usually in E09), not by this pipeline.
4. Ask before pushing, opening a PR, or merging.

## Reporting status

Asked "where is E04?" or "what's left?", read the `EPIC.md` ledgers — do not infer status from git
log or from the presence of code. The ledger is what the pipeline maintains; a mismatch between it
and the branch is itself worth reporting.
