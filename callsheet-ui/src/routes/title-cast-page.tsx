/**
 * Tag a cast member on a title and invite them (E01-S03).
 *
 * The screen exists to make one promise legible before it is made: a tagged artist sees
 * only the mentions of this title that also name them. That sentence is rendered above
 * the form, not in a tooltip, because the owner is granting access to a third party and
 * the story makes stating the scope a precondition of sending the invitation.
 *
 * The artist is picked from the title's own cast and crew rather than typed free-hand.
 * The server enforces the same rule; this is the copy of it that lets the form explain
 * itself without a round trip.
 *
 * UI invariants: no aggregate (A n/a), no mention text (B n/a), no AI-to-post path
 * (C n/a — this is an access grant, and untagging still confirms because it is
 * irreversible for the person losing access). Invariant D applies: membership status is
 * neutral chrome, handled in `TitleMembershipList`.
 */

import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { ErrorState, LoadingState } from '@/components/ui/status-message'
import { TitleMembershipList } from '@/components/ui/title-membership-list'
import { useCurrentUser } from '@/hooks/use-current-user'
import { useResendTitleInvitation } from '@/hooks/use-title-invitations'
import { useTagArtist, useTitleMemberships, useUntagArtist } from '@/hooks/use-title-memberships'
import { useTitle } from '@/hooks/use-titles'
import { buildTitleAcceptanceUrl } from '@/lib/invitations'
import { hasMeaningfulContent, parseTermList } from '@/lib/title-identity'
import type { Title, TitleMembership } from '@/types/api'

/** The people the title's identity set already names — the only taggable candidates. */
const PERSON_TERM_TYPES = new Set(['cast', 'director', 'music_director'])

export const TAGGED_ARTIST_SCOPE_NOTICE =
  'A tagged artist sees only mentions of this title that also mention them. They cannot ' +
  'edit title setup, and they cannot see anything else on your slate.'

function castCandidates(title: Title): string[] {
  const seen = new Set<string>()
  return title.terms
    .filter((term) => PERSON_TERM_TYPES.has(term.term_type))
    .map((term) => term.value)
    .filter((value) => {
      const key = value.toLocaleLowerCase()
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
}

function TagArtistForm({ title }: { title: Title }) {
  const tagArtist = useTagArtist(title.id)
  const candidates = castCandidates(title)

  const [artistName, setArtistName] = useState('')
  const [contactEmail, setContactEmail] = useState('')
  const [contactHandle, setContactHandle] = useState('')
  const [nameVariants, setNameVariants] = useState('')
  const [taggedName, setTaggedName] = useState<string | null>(null)

  const hasContact = hasMeaningfulContent(contactEmail) || hasMeaningfulContent(contactHandle)
  const isSubmittable = hasMeaningfulContent(artistName) && hasContact && !tagArtist.isPending

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!isSubmittable) return

    tagArtist.mutate(
      {
        artist_name: artistName,
        contact_email: hasMeaningfulContent(contactEmail) ? contactEmail.trim() : null,
        contact_handle: hasMeaningfulContent(contactHandle) ? contactHandle.trim() : null,
        name_variants: parseTermList(nameVariants),
        handles: [],
      },
      {
        onSuccess: (created) => {
          setTaggedName(created.artist?.display_name ?? created.invited_email)
          setArtistName('')
          setContactEmail('')
          setContactHandle('')
          setNameVariants('')
        },
      },
    )
  }

  if (candidates.length === 0) {
    return (
      <p className="text-ink-400 text-sm">
        This title has no cast or crew recorded yet. Add the lead cast to the title&rsquo;s identity
        set first — tagging grants access to someone the title already names.
      </p>
    )
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="border-ink-200 space-y-4 rounded-lg border bg-white p-5"
    >
      {/* The story's fourth Given: the screen states the scope before the invite goes out. */}
      <p className="border-ink-200 bg-ink-50 text-ink-600 rounded-md border px-3 py-2 text-xs">
        {TAGGED_ARTIST_SCOPE_NOTICE}
      </p>

      <label className="block">
        <span className="text-ink-600 block text-xs font-medium">Who are you tagging?</span>
        <select
          value={artistName}
          onChange={(event) => setArtistName(event.target.value)}
          required
          className="border-ink-200 focus:border-brand-500 mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none"
        >
          <option value="">Pick from this title&rsquo;s cast and crew…</option>
          {candidates.map((candidate) => (
            <option key={candidate} value={candidate}>
              {candidate}
            </option>
          ))}
        </select>
      </label>

      <label className="block">
        <span className="text-ink-600 block text-xs font-medium">Their email address</span>
        <input
          type="email"
          value={contactEmail}
          onChange={(event) => setContactEmail(event.target.value)}
          placeholder="actor@example.com"
          className="border-ink-200 focus:border-brand-500 mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none"
        />
      </label>

      <label className="block">
        <span className="text-ink-600 block text-xs font-medium">
          …or a handle you can reach them on
        </span>
        <input
          type="text"
          value={contactHandle}
          onChange={(event) => setContactHandle(event.target.value)}
          placeholder="@theiractualhandle"
          className="border-ink-200 focus:border-brand-500 mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none"
        />
        <span className="text-ink-400 mt-1 block text-xs">
          One of the two is enough. An invitation sent to a handle has to be passed on by hand —
          only an email address can be matched when they accept.
        </span>
      </label>

      <label className="block">
        <span className="text-ink-600 block text-xs font-medium">
          Other spellings of their name (optional)
        </span>
        <input
          type="text"
          value={nameVariants}
          onChange={(event) => setNameVariants(event.target.value)}
          placeholder="Anirudh Ravichandran, Anirudh Ravichander"
          className="border-ink-200 focus:border-brand-500 mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none"
        />
        <span className="text-ink-400 mt-1 block text-xs">
          Comma separated. They can correct these themselves when they accept.
        </span>
      </label>

      <button
        type="submit"
        disabled={!isSubmittable}
        className="bg-brand-500 hover:bg-brand-600 w-full rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
      >
        {tagArtist.isPending ? 'Sending…' : 'Tag and send invitation'}
      </button>

      {!hasContact && hasMeaningfulContent(artistName) && (
        <p className="text-ink-400 text-xs">
          Add an email address or a handle so the invitation has somewhere to go.
        </p>
      )}

      {tagArtist.isError && <ErrorState error={tagArtist.error} />}
      {taggedName && (
        // Deliberately not an acceptance link. The organization-invitation link this
        // screen could reuse redeems against a different table, so it would 404 for a
        // tagged artist — the acceptance flow for a title membership is E01-S04, and the
        // link belongs on this screen only once there is an endpoint behind it.
        <p className="border-ink-200 bg-ink-50 text-ink-600 rounded-md border px-3 py-2 text-xs">
          {taggedName} is tagged and listed below as invited. They get access once they accept.
        </p>
      )}
    </form>
  )
}

export function TitleCastPage() {
  const { titleId } = useParams<{ titleId: string }>()
  const currentUser = useCurrentUser()
  const title = useTitle(titleId)
  const memberships = useTitleMemberships(titleId)
  const untagArtist = useUntagArtist(titleId)
  const resendInvitation = useResendTitleInvitation(titleId)
  const [issuedLink, setIssuedLink] = useState<{ url: string; recipient: string } | null>(null)

  function handleResend(membership: TitleMembership) {
    resendInvitation.mutate(membership.id, {
      onSuccess: (reissued) => {
        setIssuedLink({
          url: buildTitleAcceptanceUrl(reissued.token, globalThis.location?.origin ?? ''),
          recipient: reissued.invited_email ?? reissued.artist?.display_name ?? 'the tagged artist',
        })
      },
    })
  }

  function handleUntag(membership: TitleMembership) {
    const name = membership.artist?.display_name ?? 'this artist'
    // Irreversible for the person losing access, so it is confirmed by name — the same
    // bar E01-S06 sets for revoking an agency.
    const isConfirmed = globalThis.confirm(
      `Remove ${name} from this title? They lose access immediately. Anything they have ` +
        `already exported is not recalled.`,
    )
    if (isConfirmed) untagArtist.mutate(membership.id)
  }

  if (currentUser.isPending || title.isPending) return <LoadingState label="Loading title…" />
  if (currentUser.isError) return <ErrorState error={currentUser.error} />
  if (title.isError) return <ErrorState error={title.error} />
  if (!title.data) return <ErrorState error={new Error('Title not found')} />

  const membership = currentUser.data?.memberships.find(
    (candidate) => candidate.organization.id === title.data.organization_id,
  )
  const isOwner = membership?.role === 'owner'

  return (
    <section className="mx-auto max-w-2xl space-y-6">
      <div>
        <Link to="/" className="text-ink-400 hover:text-ink-900 text-xs">
          ← Back to titles
        </Link>
        <h1 className="mt-2 text-xl font-semibold tracking-tight">{title.data.name}</h1>
        <p className="text-ink-600 mt-1 text-sm">Cast access</p>
      </div>

      {isOwner ? (
        <TagArtistForm title={title.data} />
      ) : (
        <p className="text-ink-400 text-sm">
          Only an owner of this organization can tag an artist on this title.
        </p>
      )}

      <div className="border-ink-200 space-y-3 rounded-lg border bg-white p-5">
        <h2 className="text-sm font-semibold">Tagged on this title</h2>
        {memberships.isPending && <LoadingState label="Loading access…" />}
        {memberships.isError && <ErrorState error={memberships.error} />}
        {memberships.data && (
          <TitleMembershipList
            memberships={memberships.data.memberships}
            canManage={isOwner}
            onUntag={handleUntag}
            isUntagging={untagArtist.isPending}
            onResend={handleResend}
            isResending={resendInvitation.isPending}
          />
        )}
        {resendInvitation.isError && <ErrorState error={resendInvitation.error} />}
        {issuedLink && (
          <div className="border-ink-200 bg-ink-50 rounded-md border px-4 py-3">
            <p className="text-sm font-medium">Send this link to {issuedLink.recipient}</p>
            <p className="text-ink-600 mt-1 text-xs">
              Shown once, and it replaces any link issued before it. No email is sent yet — copy it
              now.
            </p>
            <code className="text-ink-900 mt-2 block font-mono text-xs break-all">
              {issuedLink.url}
            </code>
          </div>
        )}
        {untagArtist.isError && <ErrorState error={untagArtist.error} />}
      </div>
    </section>
  )
}
