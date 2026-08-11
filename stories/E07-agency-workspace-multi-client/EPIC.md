# Epic E07 — Agency Workspace & Multi-Client Reporting

**Phase:** 3
**Source:** Concept note §4 (P3), §5.4, §9 (Phase 3)

## Epic hypothesis

**We believe that** giving agencies one workspace across all their clients, with hard access
boundaries and repeatable branded reporting
**will result in** agencies replacing spreadsheet-and-screenshot reporting with the platform,
**We will know we are right when** an agency runs its recurring client reporting from the product for
two consecutive reporting cycles without falling back to manual decks.

## Why this epic exists

Agencies juggle multiple celebrity and title clients with spreadsheet-and-screenshot reporting. They
are also the highest-leverage sales channel — one agency brings several titles and artists with it.

Two things make or break agency adoption:

1. **Access boundaries that hold.** An agency handling competing studios cannot be one misconfigured
   query away from leaking one client's numbers into another's report.
2. **Reporting that survives contact with a client meeting.** The report is the agency's deliverable,
   so it must carry scope and caveats (E05-S03, E05-S08) into a branded artefact.

## Personas served

- **P3 Social Media Management Agency** — the workspace owner.
- **P1 / P2** — as the agency's clients, granting scoped access via E01-S05.

## Stories

| ID | Summary | Phase |
|---|---|---|
| E07-S01 | Switch between clients without logging out | 3 |
| E07-S02 | See a portfolio view across every client I manage | 3 |
| E07-S03 | Guarantee one client's data never appears in another's view | 3 |
| E07-S04 | Schedule a recurring branded client report | 3 |

## Dependencies

- **Blocked by:** E01-S05 / E01-S06 (scoped grants and revocation), E05 (dashboard components),
  E08 (digest infrastructure reused for scheduled reports).

## Out of scope

- Agency-side billing of their own clients.
- Influencer outreach execution and campaign management (out of scope for v1, §5).
- Agencies creating titles on behalf of a studio without a grant.
