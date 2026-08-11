### User Story E08-S05:

- **Summary:** Get one morning email covering every client I manage

**Epic:** E08 — Alerts & Digests
**Phase:** 3
**Source:** Concept note §4 P3, §5.5

#### Use Case:
- **As an** agency account manager with eight client entities
- **I want to** receive a single daily digest summarising all of them
- **so that** I start the day knowing which client to call first, without eight separate emails to
  read and reconcile

#### Acceptance Criteria:
- **Scenario:** Account manager receives the combined morning digest
- **Given:** my agency holds active grants on eight entities across six clients
- **and Given:** the agency digest lists one line per entity with volume change, organic sentiment
  direction, and open alerts, grouped by client
- **and Given:** entities are ordered by how much they moved rather than alphabetically
- **and Given:** the digest re-checks grants at send time and omits any entity I no longer have
  access to
- **When:** the digest sends in the morning
- **Then:** I receive one email covering only my currently-granted entities, from which I can open
  any of them directly in the workspace

#### Notes
- This is an internal agency-facing artefact and must never be forwarded to a client — it spans
  clients by design. Label it as internal in the email itself.
- Client-facing reporting is E07-S04, which is single-client and branded.
- Grant re-check at send time is the same leak-prevention rule as E07-S03/E07-S04.

#### Out of scope
- Client-facing versions of this digest.
- Cross-client aggregate metrics.
