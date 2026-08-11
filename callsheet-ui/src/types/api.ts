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
