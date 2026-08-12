/** Types mirroring the backend's Pydantic schemas. Keep in sync with `app/schemas/`. */

import type { CadencePhase } from '@/lib/cadence-phase'

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

export type TitleTermType =
  | 'alias'
  | 'hashtag'
  | 'cast'
  | 'director'
  | 'music_director'
  /** A term that disqualifies a post rather than collecting one. */
  | 'exclusion'

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
  /** Normalised terms that disqualify a post from this title. */
  excluded_terms: string[]
  has_anchor_term: boolean
  created_at: string
  updated_at: string
}

/** Access granted on a single title rather than the whole organization (E01-S03). */
export type TitleRole = 'tagged_artist' | 'agency_manager'

export type TitleMembershipStatus = 'pending' | 'active' | 'revoked'

export type ArtistTermType = 'name_variant' | 'handle'

export interface ArtistTerm {
  term_type: ArtistTermType
  value: string
  normalized_value: string
  /** Which network a handle belongs to. Null for a name variant. */
  platform: string | null
}

export interface Artist {
  id: string
  display_name: string
  terms: ArtistTerm[]
}

/**
 * What a membership lets its holder see, derived server-side from the role.
 *
 * Rendered before the invitation goes out, so the owner sees the restriction they are
 * granting rather than being told about it afterwards.
 */
export interface MembershipScope {
  can_see_only_mentions_naming_subject: boolean
  can_edit_title_setup: boolean
  summary: string
}

/** The agency a title is shared with (E01-S05). */
export interface SharedOrganization {
  id: string
  name: string
  slug: string
}

export type AccessAuditAction = 'granted' | 'revoked'

/** One recorded change to who can see a title. Append-only. */
export interface AccessAuditEvent {
  id: string
  action: AccessAuditAction
  role: TitleRole
  actor_user_id: string
  subject_organization_id: string | null
  subject_user_id: string | null
  /** Denormalised, so the row still reads after the organization or artist is gone. */
  subject_name: string
  /**
   * The event's own timestamp and sort key. Split from `created_at` because that column's
   * server default resolves to whole seconds, so several changes to one title could tie
   * and read back out of order.
   */
  occurred_at: string
}

export interface AgencyShareCreate {
  agency_organization_id: string
}

export interface TitleMembership {
  id: string
  title_id: string
  role: TitleRole
  status: TitleMembershipStatus
  artist: Artist | null
  /** Set for an agency grant; exactly one of this and `artist` is present. */
  subject_organization: SharedOrganization | null
  invited_email: string | null
  invited_handle: string | null
  scope: MembershipScope
  /** Null for an agency grant — nothing was ever sent. */
  last_sent_at: string | null
  accepted_at: string | null
  created_at: string
}

/** The mint-time response only: `token` is returned once and never listed. */
export interface TitleMembershipCreated extends TitleMembership {
  token: string
}

export interface TitleMembersView {
  memberships: TitleMembership[]
}

export interface ArtistHandleInput {
  platform: string
  handle: string
}

export interface TaggedArtistCreate {
  artist_name: string
  contact_email?: string | null
  contact_handle?: string | null
  name_variants: string[]
  handles: ArtistHandleInput[]
}

/**
 * What the invited artist is shown before committing (E01-S04).
 *
 * `name_variants` and `handles` are what the production house guessed. Every one of them
 * is editable — the artist is the only person who knows which spellings are theirs.
 */
export interface TitleInvitationPreview {
  title_name: string
  organization_name: string
  artist_display_name: string
  invited_email: string | null
  name_variants: string[]
  handles: ArtistHandleInput[]
  scope: MembershipScope
  /** Server-supplied, so the promise the API makes and the sentence shown are one string. */
  privacy_notice: string
}

/** The confirmed set replaces the guess wholesale — a delta could not express a removal. */
export interface TitleInvitationAccept {
  token: string
  name_variants: string[]
  handles: ArtistHandleInput[]
}

export type CollectionRunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'skipped'

/**
 * Whether a title is collecting, and when it last did (E03-S01).
 *
 * There is no field here that starts collection, because nothing starts it — a title
 * begins collecting because it exists. The only question this answers is whether an empty
 * screen means *nothing yet* or *nothing working*, which look identical and need different
 * things from the person reading them.
 */
export interface TitleCollectionStatus {
  title_id: string
  /**
   * Every post collected, with **no account-type segmentation applied** — organic, trade,
   * owned media and promotional counted together. Segmentation is E04-S03. Until then this
   * is a measure of activity and must never be rendered as one of public conversation.
   */
  unsegmented_mention_count: number
  finished_run_count: number
  /** ISO instant, or null before the first cycle finishes. */
  last_finished_at: string | null
  last_run_status: CollectionRunStatus | null
  /** Only ever set for a genuine failure — a skipped cycle is an explanation, not a fault. */
  last_run_failure_reason: string | null
  next_run_at: string | null
  /**
   * The rate this title is on **now**, from its cadence phase (E03-S02) — not the rate the
   * queued cycle was stamped with. A title that has just crossed into its release-surge
   * window reads as surging on the next render rather than after the next poll.
   */
  polls_per_day: number
  cadence_phase: CadencePhase
  /** True when observed volume, not the calendar, is what raised this title's rate. */
  is_volume_escalated: boolean
  latest_mention_posted_at: string | null
  /** Set up, scheduled, and nothing has landed yet — the honest empty state. */
  is_awaiting_first_results: boolean
  /** Nothing is queued. This title will never collect again without intervention. */
  is_stalled: boolean
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
  /** Seeded at setup from preview posts marked "not my title" (E02-S03). */
  exclusions: string[]
  poster_url?: string | null
}

/** The unsaved identity set a preview runs against. No title id — nothing exists yet. */
export interface TitlePreviewRequest {
  name: string
  aliases: string[]
  hashtags: string[]
  lead_cast: string[]
  directors: string[]
  music_directors: string[]
}

/**
 * One sampled post. Nothing here has been through the analysis pipeline (E04), so there
 * is no sentiment, no account type, and no detected language — only what the platform
 * claimed and what the identity set explains.
 */
export interface PreviewPost {
  id: string
  author_handle: string
  author_display_name: string
  text: string
  posted_at: string
  permalink: string | null
  /** The platform's own tag, unverified — wrong on roughly half the non-English sample. */
  platform_reported_language: string | null
  /** Identity terms found in the post — why it is in the sample. */
  matched_terms: string[]
  /** Hashtags the identity set does not claim — exclusion candidates. */
  candidate_exclusion_terms: string[]
}

export interface TitlePreview {
  platform: string
  query: string
  post_limit: number
  posts: PreviewPost[]
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
