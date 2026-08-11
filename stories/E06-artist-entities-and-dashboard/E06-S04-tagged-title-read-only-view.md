### User Story E06-S04:

- **Summary:** See the film's conversation, but only the part that's about me

**Epic:** E06 — Artist Entities & Artist Dashboard
**Phase:** 2
**Source:** Concept note §4 P2 ("tagged titles read-only, filtered to conversation about the title that mentions me")

#### Use Case:
- **As an** actor tagged on a film by its production house
- **I want to** see the film's conversation narrowed to posts that mention me
- **so that** I understand my contribution to the film's reception without wading through a full
  campaign dashboard that isn't mine to manage

#### Acceptance Criteria:
- **Scenario:** Artist opens a title they were tagged on
- **Given:** a production house has tagged me on their title and I have accepted
- **and Given:** the title appears in my entity list marked read-only
- **and Given:** opening it shows the title's conversation filtered to mentions that match my
  identity set
- **and Given:** title setup, alias approval, exclusions, and member management are not available to me
- **When:** I open the tagged title
- **Then:** I see volume, sentiment, themes, and mentions for the intersection of that title and me,
  with no ability to change the title's configuration

#### Notes
- The intersection filter is what makes this different from the studio's own dashboard — the artist
  never sees the film's full corpus, only their slice of it.
- The role filter (E06-S03) applies here too and defaults to "this title as performer".

#### Out of scope
- Artist visibility into the title's overall sentiment or the studio's other titles.
- Artist ability to dispute or annotate the title's numbers.
