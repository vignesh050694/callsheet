/** Types mirroring the backend's Pydantic schemas. Keep in sync with `app/schemas/`. */

export interface Page<TItem> {
  items: TItem[]
  total: number
  limit: number
  offset: number
}

export interface HealthResponse {
  status: string
  environment: string
  version: string
}

export type OrganizationType = 'production_house' | 'agency'

export interface Organization {
  id: string
  name: string
  slug: string
  organization_type: OrganizationType
  created_at: string
  updated_at: string
}

export interface OrganizationCreate {
  name: string
  slug: string
  organization_type: OrganizationType
}

export type MembershipRole = 'owner' | 'viewer'

export type InvitationStatus = 'pending' | 'accepted' | 'cancelled'

export interface Invitation {
  id: string
  email: string
  role: MembershipRole
  status: InvitationStatus
  last_sent_at: string
  created_at: string
}

/** The mint-time response only: `token` is returned once and never listed. */
export interface InvitationCreated extends Invitation {
  token: string
}

export interface Member {
  user_id: string
  email: string
  display_name: string
  role: MembershipRole
  joined_at: string
}

export interface MembersView {
  members: Member[]
  pending_invitations: Invitation[]
}

export interface InvitationCreate {
  email: string
  role: MembershipRole
}

export type TitleTermType = 'alias' | 'hashtag' | 'cast' | 'director' | 'music_director'

export interface TitleTerm {
  term_type: TitleTermType
  value: string
}

/** Campaign beat. `phase` is derived server-side from the title's current release date. */
export interface TitleMilestone {
  id: string
  name: string
  /** ISO `YYYY-MM-DD`. Never parse this into a `Date` — see `lib/release-phase.ts`. */
  occurs_on: string
  phase: ReleasePhaseValue
}

export type ReleasePhaseValue = 'pre_release' | 'post_release'

export interface TitleMilestoneInput {
  name: string
  occurs_on: string
}

export interface Title {
  id: string
  organization_id: string
  name: string
  /** ISO `YYYY-MM-DD`. The boundary every time-series splits on. */
  release_date: string
  milestones: TitleMilestone[]
  poster_url: string | null
  terms: TitleTerm[]
  /** The normalised identity set collection queries against — never the bare name. */
  collection_terms: string[]
  has_anchor_term: boolean
  created_at: string
  updated_at: string
}

export interface TitleCreate {
  name: string
  release_date: string
  milestones: TitleMilestoneInput[]
  aliases: string[]
  hashtags: string[]
  lead_cast: string[]
  directors: string[]
  music_directors: string[]
  poster_url?: string | null
}

/** PUT body: replaces the schedule wholesale, and touches no identity terms. */
export interface TitleScheduleUpdate {
  release_date: string
  milestones: TitleMilestoneInput[]
}

export interface User {
  id: string
  email: string
  display_name: string
  is_email_verified: boolean
  created_at: string
  updated_at: string
}

export interface Membership {
  id: string
  role: MembershipRole
  organization: Organization
  created_at: string
}

export interface CurrentUser {
  user: User
  memberships: Membership[]
}
