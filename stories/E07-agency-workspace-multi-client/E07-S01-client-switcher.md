### User Story E07-S01:

- **Summary:** Move between client accounts in one click instead of juggling logins

**Epic:** E07 — Agency Workspace & Multi-Client Reporting
**Phase:** 3
**Source:** Concept note §4 P3 (multi-client workspace, client switching)

#### Use Case:
- **As an** agency account manager handling six film and artist clients at once
- **I want to** switch between my clients from a single workspace
- **so that** I can answer a client's question in the moment instead of hunting for the right
  credentials for each account

#### Acceptance Criteria:
- **Scenario:** Account manager switches from one client's title to another's during a call
- **Given:** my agency organization has been granted access to entities belonging to six clients
- **and Given:** the workspace header has a client switcher listing exactly the clients I have
  active grants for
- **and Given:** switching preserves the screen I am on but not the previous client's filters or data
- **and Given:** the active client is visible on every screen and in every export
- **When:** I switch from Client A's title to Client B's title
- **Then:** the dashboard reloads scoped entirely to Client B, with no Client A figures, filters,
  or cached rows visible anywhere on the page

#### Notes
- "Preserve the screen, discard the state" is deliberate: a filter carried across clients is how a
  misleading screenshot gets taken.
- Clients whose grant has been revoked (E01-S06) disappear from the switcher immediately.

#### Out of scope
- Cross-client comparison in a single chart (E07-S02 handles portfolio-level views deliberately).
- Agency-created client accounts without a grant from the client.
