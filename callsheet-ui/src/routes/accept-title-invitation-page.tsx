/**
 * Accept a title invitation and confirm the identity set (E01-S04).
 *
 * The correction step is the story, not a formality. The production house guessed these
 * spellings off a cast sheet; the artist is the only person who knows which are theirs.
 * So the variants arrive pre-filled and every one is editable or removable, and the
 * button says "confirm" rather than "accept" — what is being agreed to is the identity
 * set, not just the invitation.
 *
 * Accepting is an explicit action rather than something that happens on load, for the
 * reason the organization accept page documents: a prefetching mail client must not be
 * able to consume an invitation on the recipient's behalf. Previewing is safe because
 * the server treats it as read-only.
 *
 * UI invariants: no aggregate (A n/a), no mention text (B n/a), no AI-to-post path
 * (C n/a). Invariant D: nothing here encodes meaning in colour.
 */

import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { ErrorState, LoadingState } from '@/components/ui/status-message'
import { useAcceptTitleInvitation, useTitleInvitationPreview } from '@/hooks/use-title-invitations'
import { hasMeaningfulContent, parseTermList } from '@/lib/title-identity'
import type { ArtistHandleInput, TitleInvitationPreview } from '@/types/api'

const TOKEN_QUERY_PARAM = 'token'

function MissingToken() {
  return (
    <div className="border-ink-200 mx-auto max-w-lg rounded-lg border bg-white px-6 py-8 text-center">
      <p className="text-sm font-medium">This link is incomplete</p>
      <p className="text-ink-600 mt-2 text-sm">
        The invitation link needs its token. Ask the production house to resend it.
      </p>
    </div>
  )
}

/** Handles round-trip as `platform:handle` lines, so one textarea can edit the whole set. */
function handlesToText(handles: ArtistHandleInput[]): string {
  return handles.map((entry) => `${entry.platform}: ${entry.handle}`).join('\n')
}

function parseHandles(rawValue: string): ArtistHandleInput[] {
  return rawValue
    .split('\n')
    .map((line) => {
      const separatorIndex = line.indexOf(':')
      if (separatorIndex === -1) return null
      const platform = line.slice(0, separatorIndex).trim()
      const handle = line.slice(separatorIndex + 1).trim()
      if (!hasMeaningfulContent(platform) || !hasMeaningfulContent(handle)) return null
      return { platform, handle }
    })
    .filter((entry): entry is ArtistHandleInput => entry !== null)
}

function ConfirmIdentityForm({
  token,
  preview,
}: {
  token: string
  preview: TitleInvitationPreview
}) {
  const navigate = useNavigate()
  const acceptInvitation = useAcceptTitleInvitation()

  const [nameVariants, setNameVariants] = useState('')
  const [handlesText, setHandlesText] = useState('')

  // Seeded from the preview once it arrives, then owned by the form — retyping a variant
  // must not be undone by a refetch.
  useEffect(() => {
    setNameVariants(preview.name_variants.join(', '))
    setHandlesText(handlesToText(preview.handles))
  }, [preview])

  const confirmedVariants = parseTermList(nameVariants)
  const confirmedHandles = parseHandles(handlesText)
  const hasIdentity = confirmedVariants.length > 0 || confirmedHandles.length > 0

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!hasIdentity || acceptInvitation.isPending) return

    acceptInvitation.mutate(
      { token, name_variants: confirmedVariants, handles: confirmedHandles },
      { onSuccess: () => void navigate('/', { replace: true }) },
    )
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="border-ink-200 mt-6 space-y-4 rounded-lg border bg-white p-5"
    >
      {/* The story's fourth Given, in the server's own words. */}
      <p className="border-ink-200 bg-ink-50 text-ink-600 rounded-md border px-3 py-2 text-xs">
        {preview.privacy_notice}
      </p>

      <label className="block">
        <span className="text-ink-600 block text-xs font-medium">Names you are referred to by</span>
        <input
          type="text"
          value={nameVariants}
          onChange={(event) => setNameVariants(event.target.value)}
          className="border-ink-200 focus:border-brand-500 mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none"
        />
        <span className="text-ink-400 mt-1 block text-xs">
          Comma separated. {preview.organization_name} entered these — correct anything that is
          wrong, add spellings they missed, and delete any that are not you.
        </span>
      </label>

      <label className="block">
        <span className="text-ink-600 block text-xs font-medium">Your handles</span>
        <textarea
          value={handlesText}
          onChange={(event) => setHandlesText(event.target.value)}
          rows={3}
          placeholder={'instagram: @yourhandle\nx: @yourhandle'}
          className="border-ink-200 focus:border-brand-500 mt-1 w-full rounded-md border px-3 py-2 font-mono text-sm outline-none"
        />
        <span className="text-ink-400 mt-1 block text-xs">
          One per line, as <code className="font-mono">platform: handle</code>.
        </span>
      </label>

      <button
        type="submit"
        disabled={!hasIdentity || acceptInvitation.isPending}
        className="bg-brand-500 hover:bg-brand-600 w-full rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
      >
        {acceptInvitation.isPending ? 'Confirming…' : 'Confirm and accept'}
      </button>

      {!hasIdentity && (
        <p className="text-ink-400 text-xs">
          Keep at least one name or handle — it is what the mentions of you are matched on.
        </p>
      )}

      {acceptInvitation.isError && <ErrorState error={acceptInvitation.error} />}
    </form>
  )
}

export function AcceptTitleInvitationPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get(TOKEN_QUERY_PARAM)
  const preview = useTitleInvitationPreview(token)

  if (!token) return <MissingToken />
  if (preview.isPending) return <LoadingState label="Loading your invitation…" />
  if (preview.isError) return <ErrorState error={preview.error} />

  return (
    <section className="mx-auto max-w-lg">
      <h1 className="text-xl font-semibold tracking-tight">{preview.data.title_name}</h1>
      <p className="text-ink-600 mt-1 text-sm">
        {preview.data.organization_name} tagged you on this title as{' '}
        {preview.data.artist_display_name}.
      </p>
      <p className="text-ink-600 mt-2 text-sm">{preview.data.scope.summary}</p>

      <ConfirmIdentityForm token={token} preview={preview.data} />
    </section>
  )
}
