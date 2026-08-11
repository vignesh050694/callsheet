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
| E01-S02 | Invite a teammate into the organization with a role | 1 | todo | — |
| E01-S03 | Tag an artist on a title and invite them | 2 | todo | — |
| E01-S04 | Artist accepts an invite and links their profile | 2 | todo | — |
| E01-S05 | Grant an agency scoped access to a single title | 3 | todo | — |
| E01-S06 | Revoke access when an engagement ends | 3 | todo | — |

## Dependencies

- **Blocks:** E02 (titles must belong to an org), E06, E07.
- **Blocked by:** nothing.

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
