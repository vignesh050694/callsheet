### User Story E06-S03:

- **Summary:** Separate praise for my acting, my directing, and my next project into three questions

**Epic:** E06 — Artist Entities & Artist Dashboard
**Phase:** 2
**Source:** Concept note §4 (validated complication — the three-way Lokesh case), §9 Phase 2

#### Use Case:
- **As an** artist who acts in one film, directs others, and has an unrelated announced project
- **I want to** filter mentions of me by which of those roles the post is actually about
- **so that** reaction to my performance in this film is not blended with excitement about a project
  I have not started shooting

#### Acceptance Criteria:
- **Scenario:** Artist separates lead-actor mentions from director-brand and future-project mentions
- **Given:** my artist entity is tagged on a title where I am the lead actor
- **and Given:** the corpus for that title also contains posts about my directing reputation and
  posts about an unrelated upcoming project of mine
- **and Given:** the pipeline assigns each mention of me a role context — this title as performer,
  general/career reputation, or another named project
- **and Given:** my dashboard has a role filter defaulting to this title as performer
- **When:** I switch the role filter to the unrelated upcoming project
- **Then:** volume, sentiment, and themes recompute against only the mentions about that project,
  and the mentions feed shows only those posts

#### Notes
- This is the concrete, testable form of the concept note's validated complication: in the *DC*
  corpus Lokesh Kanagaraj is simultaneously lead actor, celebrated director, and `#AA23`
  collaborator — and `#AA23` posts surface *inside* DC-anchored results.
- Role context should be derivable from the artist's declared projects plus post content, and must
  be correctable by the artist when it gets it wrong.
- Needs its own accuracy measurement before this dashboard is trusted, on the same pattern as the
  §9 gates.

#### Out of scope
- Automatic discovery of an artist's unannounced projects.
- Role attribution for crew credits beyond the artist's declared roles.
