### User Story E04-S03:

- **Summary:** Separate real audience voices from trade, owned, and promo accounts

**Epic:** E04 — AI Analysis Pipeline
**Phase:** 1
**Source:** Concept note §6.3 ("the single most important product finding"), §3, §8 risk #8, §9 gate ≥ 0.85

#### Use Case:
- **As a** production house owner who wants to know what the public thinks
- **I want to** have every mention classified by the kind of account that posted it
- **so that** I am not shown my own distributors' promotions and a box-office tracker's headlines as
  if they were audience opinion

#### Acceptance Criteria:
- **Scenario:** A corpus mixing audience, trade, owned, and promotional accounts is classified
- **Given:** the corpus for my title contains individual viewers, box-office tracker accounts,
  my own production house and distributor handles, and cinema chains posting booking links
- **and Given:** the pipeline runs account-type classification after language ID and before aggregation
- **and Given:** the classifier assigns exactly one of: organic audience, trade / tracker,
  owned media, promotional
- **and Given:** the classifier uses account signals (handle, bio, follower profile, posting pattern)
  as well as post content
- **and Given:** accounts I have declared as my own during title setup are assigned owned media directly
- **When:** the corpus is classified
- **Then:** every mention carries an account type, and all downstream aggregates can be sliced by it
  with organic audience as the default view

#### Notes
- This is the wedge: "the difference between a listening tool and an intelligence tool". Incumbents
  would report the *DC* corpus as broadly positive without ever separating these four groups.
- Classification is per-account with per-post override, so a tracker account is stable across a
  campaign rather than reclassified post by post.
- Gate: **≥ 0.85 accuracy** before Phase 2.

#### Out of scope
- Bot / inauthentic-amplification detection as a distinct category (Phase 4 candidate).
- Paid-influencer disclosure detection.
