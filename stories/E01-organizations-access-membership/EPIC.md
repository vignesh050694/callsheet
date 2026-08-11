# Epic E01 — Organizations, Access & Membership

**Phase:** 1 (org + owner roles), 2 (artist tagging), 3 (agency access)
**Source:** Concept note §4 (Personas, access model), §9 (MVP), §11.3 (entity model)

## Epic hypothesis

**We believe that** giving production houses, artists, and agencies a shared workspace with explicit,
scoped memberships
**will result in** artists and agencies being invited into titles rather than emailed screenshots,
**We will know we are right when** at least one pilot title has an owner plus one non-owner member
(tagged artist or agency manager) who each viewed the dashboard in the same week.

## Why this epic exists

The concept note fixes the access model as:

```
Organization (production house | agency) → Entities (Title, Artist) → Memberships (owner, tagged artist, agency manager, viewer)
```

Every other epic depends on this. A Title Dashboard with no membership model can only ever be
single-user, and the north-star metric (weekly active entities *with an owner who viewed it*)
is unmeasurable without it.

## Personas served

- **P1 Production House** — owns the org and its titles, invites everyone else.
- **P2 Actor / Artist** — invited in, sees a restricted read-only slice.
- **P3 Agency** — its own org, granted scoped access to a client's entities.

## Stories

| ID | Summary | Phase | Status | Commit |
|---|---|---|---|---|
| E01-S01 | Create a production house organization and workspace | 1 | done | a708c43 |
| E01-S02 | Invite a teammate into the organization with a role | 1 | done | 331ba42 |
| E01-S03 | Tag an artist on a title and invite them | 2 | blocked | — |
| E01-S04 | Artist accepts an invite and links their profile | 2 | blocked | — |
| E01-S05 | Grant an agency scoped access to a single title | 3 | blocked | — |
| E01-S06 | Revoke access when an engagement ends | 3 | blocked | — |

## Dependencies

- **Blocks:** E02 (titles must belong to an org), E06, E07.
- **Blocked by:** nothing — for phase 1. Phases 2 and 3 are blocked by E02.

**Sequencing note.** E02 needs only an organization to hang a title on, which E01-S01 and
E01-S02 delivered, so E02 is unblocked. E01's own phase-2 and phase-3 stories all need a title
to exist first, so they queue up *behind* E02 rather than in front of it. The stories stay in
this epic — they are access-control work, not title setup — and resume once titles land.

## Out of scope

- SSO / SAML, org-to-org billing hierarchies, self-serve signup without invite (v1 is invite-led).
- Artist identity verification beyond invite-based linking (concept note risk #7).

## Delivery log

**Branch:** `epic/E01-organizations-access-membership`

- **E01-S01** — done · `a708c43` · 26 tests · `make check` + `npm run check` green · both READMEs
  updated. Review round 1 found two real bugs (organization routes other than POST had no
  authentication at all; slug uniqueness was check-then-insert and returned 500 instead of 409).
  Both fixed and re-reviewed. Frontend has no test runner, so the onboarding and titles screens
  have no automated coverage — verified by typecheck, build, and manual exercise only.
- **E01-S02** — done · `331ba42` · 38 tests · `make check` + `npm run check` green · both READMEs
  updated. Two review rounds. Round 1: accept had the same unguarded check-then-insert race as
  S01 (500 instead of 409), and the accept flow had no frontend at all. Round 2: the race guard
  itself crashed — `rollback()` expires ORM objects and the log line then read one. Fixed by
  reading identifiers into locals first. A vacuous test (wrong-recipient case tripped the
  verified-email check first, so it passed even with the security check removed) was found and
  rewritten; the replacement was mutation-tested to confirm it fails when the check is deleted.
  Carried limitations: no mail transport (acceptance link surfaced in the owner's UI, not
  emailed); invitations never expire; frontend has no test runner, so all screens are unverified
  by automation. The story's "sees my organization's titles" clause is verified against
  organization PATCH/DELETE as a proxy — titles arrive in E02.
- **E01-S03** — blocked · needs a title to tag an artist on ("Given: I own a title that has an
  active collection running"). Waiting on E02-S01 (create a title); the "active collection"
  Given additionally implies E03.
- **E01-S04** — blocked · needs E01-S03 ("Given: a production house has tagged me on a title").
  Its alias corrections also feed the identity set from E02-S04.
- **E01-S05** — blocked · needs titles to scope access to ("Given: my organization owns three
  titles, two of which are unannounced"). Waiting on E02-S01.
- **E01-S06** — blocked · needs E01-S05 ("Given: an agency organization currently has manager
  access to one of my titles"). The Notes say revocation "applies identically to tagged artists
  and internal viewers" — the internal-viewer half is buildable today, but the story's scenario
  is agency-scoped, so it moves as one piece rather than being split.

**Epic status:** phase 1 complete — 2/6 stories done on
`epic/E01-organizations-access-membership`. Phases 2 and 3 (4 stories) are blocked on E02 and
resume once titles exist. The epic's hypothesis is not yet measurable: it needs a pilot title
with an owner plus one non-owner member, and titles arrive in E02.
