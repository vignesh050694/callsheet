/**
 * Accept an invitation (E01-S02).
 *
 * The other half of the invite flow: the colleague opens the link they were sent and
 * lands here with the token in the query string. Accepting is an explicit action rather
 * than something that happens on page load — joining an organization should not be a
 * side effect of clicking a link in an email, and a prefetching mail client must not be
 * able to consume the invitation on the recipient's behalf.
 */

import { useNavigate, useSearchParams } from 'react-router-dom'

import { ErrorState } from '@/components/ui/status-message'
import { useAcceptInvitation } from '@/hooks/use-members'

const TOKEN_QUERY_PARAM = 'token'

function MissingToken() {
  return (
    <div className="border-ink-200 mx-auto max-w-lg rounded-lg border bg-white px-6 py-8 text-center">
      <p className="text-sm font-medium">This link is incomplete</p>
      <p className="text-ink-600 mt-2 text-sm">
        The invitation link needs its token. Ask whoever invited you to resend it.
      </p>
    </div>
  )
}

export function AcceptInvitationPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const acceptInvitation = useAcceptInvitation()

  const token = searchParams.get(TOKEN_QUERY_PARAM)
  if (!token) return <MissingToken />

  function handleAccept() {
    if (!token) return
    acceptInvitation.mutate(token, { onSuccess: () => void navigate('/', { replace: true }) })
  }

  return (
    <section className="mx-auto max-w-lg">
      <h1 className="text-xl font-semibold tracking-tight">Join this workspace</h1>
      <p className="text-ink-600 mt-1 text-sm">
        You have been invited into a production house workspace. Accepting adds you to it with the
        role you were invited under.
      </p>

      <div className="border-ink-200 mt-6 rounded-lg border bg-white p-5">
        <button
          type="button"
          onClick={handleAccept}
          disabled={acceptInvitation.isPending}
          className="bg-brand-500 hover:bg-brand-600 w-full rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
        >
          {acceptInvitation.isPending ? 'Joining…' : 'Accept invitation'}
        </button>

        {acceptInvitation.isError && (
          <div className="mt-3">
            <ErrorState error={acceptInvitation.error} />
          </div>
        )}
      </div>

      <p className="text-ink-400 mt-3 text-xs">
        An invitation only works for the email address it was sent to.
      </p>
    </section>
  )
}
