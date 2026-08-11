### User Story E01-S01:

- **Summary:** Create a production house workspace so a studio's titles live under one owned account

**Epic:** E01 — Organizations, Access & Membership
**Phase:** 1
**Source:** Concept note §4 (access model), §9 (MVP: one org type)

#### Use Case:
- **As a** marketing head at a production house who has just been given pilot access
- **I want to** create an organization workspace for my studio
- **so that** every title we track sits under an account my studio owns and controls, instead of
  under an individual employee's personal login

#### Acceptance Criteria:
- **Scenario:** First-time production house user sets up their studio workspace
- **Given:** I have accepted a pilot invitation and verified my email
- **and Given:** I do not yet belong to any organization
- **and Given:** the onboarding screen asks me for a studio name and organization type
- **and Given:** "Production House" is an available organization type
- **When:** I enter my studio name, select "Production House", and submit the form
- **Then:** the organization is created with me recorded as its owner, and I land on an empty
  title list with a "Create your first title" call to action

#### Notes
- Organization type is stored on the record from day one even though v1 only enables Production
  House — Agency (E07) reuses the same table.
- Owner is a membership row, not a column on the org, so ownership can transfer later.

#### Out of scope
- Billing details, tax information, and plan selection (E09-S05).
- Agency organizations (E07).
