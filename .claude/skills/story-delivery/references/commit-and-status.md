# Commit format and EPIC.md status tracking

## Commit — one per story

Everything a story produced goes in a single commit: implementation, tests, docs, and the `EPIC.md`
status update. No separate "add tests" or "update docs" commits — the story is the unit.

```
<type>(<STORY_ID>): <story summary, lowercase, imperative>

Story: <STORY_PATH>
Epic:  <EPIC_ID> — <epic title>

<2–5 bullets on what changed and why, at the level of behaviour rather than files>

Tests:  <n> added — <the scenarios they cover>
Verify: <exact command> — passing
Docs:   <files updated, or "no changes needed">

Pipeline: implement=opus tests=sonnet review=sonnet docs=haiku

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

`<type>` is `feat` for new user-facing capability, `fix` for corrections to an already-`done` story,
`refactor` for internal change with no behaviour delta. The summary is the story file's **Summary**
line, trimmed.

Worked example:

```
feat(E02-S01): create a title with a rich identity set

Story: stories/E02-title-setup-identity-discovery/E02-S01-create-title-with-rich-identity.md
Epic:  E02 — Title Setup & Identity Discovery

- Title creation accepts aliases, official hashtags, and lead cast/crew alongside the name,
  and stores them as one identity set.
- Collection queries against the combined set, never the bare title name.
- Submission is blocked for a name under four characters with no anchor term.

Tests:  7 added — happy path, sub-four-character name without anchor, empty alias set,
        duplicate hashtag normalisation
Verify: cd callsheet && make check — passing
Docs:   callsheet/README.md (POST /titles payload)

Pipeline: implement=opus tests=sonnet review=sonnet docs=haiku

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

Commit only after Stage 3 returns `pass`. Never `--amend` a story commit that is already on the epic
branch — a correction is its own `fix(<STORY_ID>)` commit.

## EPIC.md — the status ledger

Two edits per story. `EPIC.md` is the only place status lives; story files stay unedited.

### 1. The Stories table

Extend the existing table with `Status` and `Commit` columns on first run:

```markdown
## Stories

| ID | Summary | Phase | Status | Commit |
|---|---|---|---|---|
| E02-S01 | Create a title with a rich identity set | 1 | done | a3f9c21 |
| E02-S02 | Anchor the title to a release date and campaign milestones | 1 | in-progress | — |
| E02-S03 | Preview live sample results before committing setup | 1 | todo | — |
| E02-S04 | Review and approve discovered alias suggestions | 1 | blocked | — |
| E02-S05 | Exclude a contaminating term from a title's results | 1 | todo | — |
```

| Status | Means |
|---|---|
| `todo` | not started |
| `in-progress` | Stage 1 running |
| `in-review` | Stage 3 running |
| `done` | committed on the epic branch, review passed, checks green |
| `blocked` | stopped — the reason is in the Delivery Log line |

A story is `done` only when its commit exists. Nothing else counts.

### 2. The Delivery Log

Append at the bottom of `EPIC.md`, newest last. Create the section on first run:

```markdown
## Delivery log

**Branch:** `epic/E02-title-setup-identity-discovery`

- **E02-S01** — done · `a3f9c21` · 7 tests · `make check` green · README updated
- **E02-S02** — in-progress · Stage 1
- **E02-S04** — blocked · reviewer rejected twice: alias suggestions need the corpus store from
  E03-S04, which is still `todo`
```

Blocked entries name the blocker specifically enough to act on. "Review failed" is not an entry.

### 3. Epic rollup

When every story is `done`, add above the Delivery Log:

```markdown
**Epic status:** complete — 5/5 stories on `epic/E02-title-setup-identity-discovery`,
awaiting merge. Gate (entity-match precision ≥ 0.85) measured by E09-S06, not yet run.
```

Do not claim the epic's gate is met. Gates are measured by their own stories; this pipeline only
records whether that measurement has happened.

### Interrupted runs

`in-progress` and `in-review` are written before their stage starts, so a run that dies leaves a
truthful ledger. On picking work back up, reconcile first: a story marked `in-progress` with no
uncommitted changes in the tree goes back to `todo`.
