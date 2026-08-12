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
| E01-S03 | Tag an artist on a title and invite them | 2 | done | c0fd6db |
| E01-S04 | Artist accepts an invite and links their profile | 2 | done | e431852 |
| E01-S05 | Grant an agency scoped access to a single title | 3 | done | 3482970 |
| E01-S06 | Revoke access when an engagement ends | 3 | done | — |

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
- **E01-S03** — done · `c0fd6db` · 12 tests · `make check` + `npm run check` + `npm run build` green.
  The blocker cleared when E02-S01 (create a title) and E03-S01 (collection starts on title
  creation) both landed, so the branch was fast-forwarded onto the E02/E03 stack — `epic/E01` was
  a strict ancestor of `epic/E03`, so no merge was needed and the history stays linear.

  Introduces the two shapes the rest of the epic needs: an `Artist` entity with its own identity
  set (separate from `users`, because a tagged artist may never hold an account), and
  `title_memberships` — access scoped to one entity rather than a whole organization. The pending
  membership *is* the invitation; it carries the capability token, so "offered access" and "has
  access" cannot disagree.

  Two review rounds. Round 1 found two real bugs. A `contact_handle` of nothing but invisible
  characters passed the schema's `str.strip()` test, collapsed to `NULL` under the service's
  `has_meaningful_content` cleaning, tripped `ck_title_membership_has_contact`, and surfaced
  through the `IntegrityError` handler as "already tagged" — on a title nobody had ever tagged.
  And the tagging screen shipped an acceptance link that could never redeem: it reused the
  organization-invitation flow, whose token lives in a different table. Round 2 confirmed both
  fixed and found a third in the same class — `invited_handle` reached a `String(300)` column
  without `ensure_fits`, so a handle of 150 "ﬃ" ligatures cleared the schema's 300-character
  limit and became 450 after NFKC, which Postgres answers with a `DataError` (a sibling of
  `IntegrityError`, so the conflict handler misses it) and the caller sees as a 500. Invisible
  under the test suite, which runs on SQLite and does not enforce VARCHAR limits.

  **Deviation from the pipeline, recorded deliberately:** the third finding was fixed and given a
  regression test without a third full review round, under the MVP instruction to relax review
  depth. The fix is one guarded call matching three existing call sites in the same file.

  Carried limitations: tagging requires the person to already be named in the title's identity set
  (cast, director, or music director) — the story's Given assumes it, and an untethered artist
  entity would have an empty slice by construction, since a tagged artist sees only mentions
  naming them. A handle-only tag is accepted but is not a verified channel: only an email address
  can be matched when the artist accepts, so the owner passes a handle invitation on by hand —
  the same limitation E01-S02 carries while there is no mail transport. **The acceptance link is
  deliberately absent from this screen**, so the minted token is not recoverable after the
  response that issued it; E01-S04 must mint a fresh token rather than assume it can surface
  S03's. Frontend still has no test runner, so the Cast access screen is verified by typecheck,
  build, and manual exercise only.
- **E01-S04** — done · `e431852` · 8 tests · `make check` + `npm run check` + `npm run build` green.

  The artist claims their entity by redeeming an invitation addressed to a verified email —
  which is the whole of identity verification in v1 (concept note risk #7), never inferred from a
  matching name. Accepting links `Artist.linked_user_id`, sets the membership's
  `subject_user_id`, and nulls the token so it cannot be replayed. The confirmed identity set
  *replaces* the production house's guess rather than merging with it, because the story's "add,
  correct, or **remove**" cannot be expressed by a merge.

  Two review rounds. Round 1 found three real bugs. The artist claim was a check-then-act with no
  database backstop, so two concurrent accepts on one artist entity would both pass and the last
  write would silently win — no error, and the entity bound to whoever committed last. That could
  not be fixed with a unique constraint, because one account legitimately holds one artist row per
  organization that tracks them, so the guard moved into the write: a conditional
  `UPDATE ... WHERE linked_user_id IS NULL` whose rowcount decides, with zero rows a conflict
  unless this account already holds the claim. A handle's `platform` skipped `ensure_fits` after
  NFKC — the third instance of that class in this epic. And the workspace gate never checked the
  shared-titles error state, so an artist whose lookup failed was routed to onboarding and invited
  to create a production house. Round 2 passed, having mutation-tested both backend fixes to
  confirm the new tests fail when the fix is removed.

  Carried limitations: a handle-only invitation cannot be accepted at all — the token alone proves
  nothing about who holds it, so v1 refuses and tells the artist to ask for an email invitation
  instead. Verified handle ownership is out of scope for E01. The raw token is returned once and
  never stored, so a lost link is recovered by re-issuing (`POST .../memberships/{id}/resend`),
  which supersedes the previous one. "Corrected variants are used for entity matching from the
  next collection run onwards" is delivered as far as this epic can take it — the corrected set is
  stored and exposed; the matching that consumes it is E04. Frontend still has no test runner, so
  the acceptance and shared-titles screens are verified by typecheck, build, and manual exercise
  only.

  **Note on the working tree:** this story was delivered alongside unrelated in-flight E03 work
  (a live Monid HTTP transport) that shares `app/api/deps.py`. Only this story's changes were
  staged; that work remains uncommitted and untouched.
- **E01-S05** — done · `3482970` · 8 tests · `make check` + `npm run check` + `npm run build` green.

  The story's real requirement is the one in its Notes — *enforcement at the query layer* — and
  the work that mattered was consolidation rather than the grant itself. Three services each held
  their own copy of "is the caller a member of the owning organization": `TitleService`,
  `CollectionStatusService`, and `TitlePreviewService`. That was correct while ownership was the
  only way in, and became a liability the moment a title could be shared, because adding the new
  case to two of three is a silent hole. `TitleAccessPolicy` is now the single answer, and every
  route taking a title id resolves through it.

  Access is held by the agency *organization*, not by named people in it, because agency staff
  change mid-engagement and the failure mode of re-inviting by hand is a departed employee who
  still has access. A grant is live immediately — there is nothing to accept, so an agency
  membership has no invitation, no contact channel, and no `last_sent_at`; both constraints that
  assumed otherwise were narrowed to the tagged-artist role rather than dropped.

  Two review rounds. Round 1 found two real bugs, one of them serious: the migration's
  `downgrade()` restored `last_sent_at` to `NOT NULL` and reinstated an unscoped contact
  constraint, neither of which an agency row can satisfy — so rollback broke the moment the
  feature was used once, which is exactly when it would be needed. Reproduced against real
  Postgres by the reviewer, fixed, and the upgrade → seed → downgrade → upgrade round trip
  re-verified against Postgres before commit. The second was a *fourth* copy of the access rule
  hiding in `list_memberships`, inside the very change that removed the other three. Round 2
  passed and flagged the old helpers as dead code, which was then removed.

  Stage 2 also found a real inconsistency before review: `/access-log` refused an agency with 403
  while its sibling `/memberships` refused with 404 — two lateral-visibility surfaces denying the
  same thing two different ways, and the 403's message spoke about editing setup on a read. Both
  now give the plain 404 a stranger gets.

  Carried limitations: sharing is per title and per agency, one request at a time — deliberate,
  since the story requires the studio to name what it shares and there is no bulk path anywhere
  in the API or UI. The grantee must already exist and be an `agency` organization; a production
  house cannot be granted the agency-manager role. Export is permitted by the role but there is
  no export feature yet to exercise it. The agency's own multi-client workspace is E07-S01, out
  of scope here — an agency manager sees shared titles through `/me/titles`. Frontend still has
  no test runner.
- **E01-S06** — done · `—` · 10 tests · `make check` + `npm run check` + `npm run build` green.

  Revocation needed almost no new enforcement: every query that resolves access already filters
  on `ACTIVE`, so flipping the status *is* the mechanism. That is also the honest limit of
  "immediate" — nothing reaches into an open browser, so a partner keeps whatever is already
  painted on their screen and fails on their next request. The row is tombstoned rather than
  deleted, because an engagement that ended is exactly what someone reconstructs later.

  Two review rounds. Round 1 found two real bugs, both reproduced. `_retag` — the path that
  revives a revoked tag — ran *before* the contact and length validation, so re-tagging a
  previously revoked artist accepted a handle that fresh tagging correctly refuses; that is the
  fourth instance of the NFKC-expansion class in this epic, and the fix extracts one validator
  both paths share. Worse, `untag` had no status guard: `DELETE` on an *accepted* membership
  returned 204, the artist's access vanished, and the access log recorded nothing — a silent,
  unaudited bypass of the very requirement this story adds, reachable by any API client even
  though the UI hid the button. Untagging is now restricted to pending invitations; ending
  accepted access must go through the audited revoke. Round 2 passed, having mutation-tested
  both fixes and enumerated every write path onto `title_memberships` to confirm which are
  audited.

  A third bug surfaced during implementation, before review: the audit log misreported its own
  order. `created_at` carries a server default — `now()` is transaction-start time on Postgres,
  whole seconds on SQLite — so grant → revoke → grant inside one second tied and fell back to a
  random UUID tiebreak, reading back as revoke → grant → grant. An audit log that gets its own
  sequence wrong is worse than none, because the wrong story is still a confident one. Events now
  carry `occurred_at`, set in Python at microsecond resolution, and that is the log's sort key.

  Also fixed here: a revoked row still occupied its unique constraint, so a client returning for
  a second engagement would have been refused as a duplicate. Sharing and tagging now reactivate
  the existing row, which keeps one history rather than splitting it across two.

  Carried limitations: the Notes say revocation "applies identically to tagged artists and
  internal viewers". The tagged-artist half is delivered — `revoke_access` is role-agnostic. The
  **internal-viewer half is not**: organization viewers live in `memberships`, a different table
  with no title to scope an audit row against, and the story's own scenario is agency-scoped.
  Removing an org member belongs with E01-S02's membership management and is deliberately not
  built here. Revocation is also not scheduled or expiring (explicitly out of scope), and
  exported reports are not recalled — stated in the confirmation dialog so the owner is not
  misled about what revocation reaches.

**Epic status:** complete — 6/6 stories done on `epic/E01-organizations-access-membership`.
Phase 1 (S01–S02) was already merged to `main` via PR #1; phases 2 and 3 (S03–S06) landed after
the E02 dependency cleared and the branch was fast-forwarded onto the E02/E03 stack.

The access model the concept note fixes is now real end to end: an organization owns titles, a
title can be shared with an artist or an agency, and every grant and revocation is recorded.
Enforcement lives in one place — `TitleAccessPolicy` — which every route taking a title id
resolves through, so a title nobody shared with you is indistinguishable from one that does not
exist.

**The hypothesis is now measurable but not yet measured.** It asks for a pilot title with an
owner plus one non-owner member who each viewed the dashboard in the same week. The membership
half exists; the *viewing* half does not, because there is no Title Dashboard until E05. Nothing
in this epic can close that, and no story here should be read as having done so.

**Sequencing note for whoever picks this up:** four of the ten bugs found across S03–S06 were the
same defect — a value reaching a length-bounded column without `ensure_fits` after NFKC
normalisation, which SQLite cannot catch because it does not enforce VARCHAR limits. It recurred
because each new write path had to remember the rule independently. A shared "clean and bound
this value" helper, or a test-suite switch to Postgres, would end the class rather than the
instance.
