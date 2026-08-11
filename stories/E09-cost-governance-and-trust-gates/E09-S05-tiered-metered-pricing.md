### User Story E09-S05:

- **Summary:** Buy a plan that fits my film's scale, from indie single to tentpole

**Epic:** E09 — Cost Governance & Trust Gates
**Phase:** 1
**Source:** Concept note §7 ("a flat per-title price does not work"; base tier + metered volume)

#### Use Case:
- **As a** production house owner whose slate ranges from a small indie release to a star vehicle
- **I want to** choose a plan whose price reflects the scale of the title I am tracking
- **so that** a small release is affordable to me and a tentpole is not sold at a loss to the
  vendor and then quietly throttled

#### Acceptance Criteria:
- **Scenario:** Owner picks a plan for a mid-budget title and later upgrades it
- **Given:** plans are offered as a base tier plus a metered volume component, banded by expected scale
- **and Given:** each tier states its included mention volume, its polling cadence in each campaign
  phase, and its overage rate
- **and Given:** a title's current usage against its included volume is visible on the dashboard
- **and Given:** approaching the included limit notifies the owner before anything is throttled
- **When:** my title's volume approaches its tier limit and I upgrade
- **Then:** the higher tier's cadence and volume allowance apply from that moment, with no gap in
  collection and no silent reduction in polling beforehand

#### Notes
- The concept note's reasoning is direct: a Rajinikanth or Vijay release is plausibly 10–20× a
  mid-budget film in volume, and both collection and analysis scale with it. A flat fee loses money
  on exactly the titles worth selling to, and prices the indie-music persona out entirely.
- The three cadence phases (dormant / campaign / release surge) give the tier structure a natural
  shape — tiers differ meaningfully in surge cadence.
- Silent throttling is the anti-goal. Notify, then throttle visibly, and say so in the UI.

#### Out of scope
- Self-serve card payment and invoicing (pilot titles are contracted manually).
- Agency reseller pricing.
