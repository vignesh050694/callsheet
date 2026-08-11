/**
 * Title setup (E02-S01).
 *
 * The form's job is to make the anchored query unavoidable. A bare short name is the
 * known failure case — it collects everything that shares the name — so the anchor
 * requirement is stated up front, not raised as an error after submission, and the
 * submit button stays disabled until the name is collectable.
 *
 * UI invariants: no aggregate, no mention text, no outbound action, nothing encoded by
 * colour, so none of the four platform invariants apply. The identity-set preview uses
 * neutral chips for the same reason — saturated colour belongs to sentiment.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { MilestoneEditor } from '@/components/ui/milestone-editor'
import { ErrorState, LoadingState } from '@/components/ui/status-message'
import { useCurrentUser } from '@/hooks/use-current-user'
import { useCreateTitle } from '@/hooks/use-titles'
import { completedMilestones, type MilestoneDraft } from '@/lib/milestones'
import { MIN_UNANCHORED_NAME_LENGTH, isNameCollectable, parseTermList } from '@/lib/title-identity'

interface TermFieldProps {
  label: string
  hint: string
  value: string
  onChange: (value: string) => void
  placeholder: string
}

function TermField({ label, hint, value, onChange, placeholder }: TermFieldProps) {
  const terms = parseTermList(value)

  return (
    <label className="block">
      <span className="text-ink-600 block text-xs font-medium">{label}</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="border-ink-200 focus:border-brand-500 mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none"
      />
      <span className="text-ink-400 mt-1 block text-xs">{hint}</span>
      {terms.length > 0 && (
        <span className="mt-1 flex flex-wrap gap-1">
          {terms.map((term) => (
            <span
              key={term}
              className="border-ink-200 text-ink-600 rounded border px-2 py-0.5 text-xs"
            >
              {term}
            </span>
          ))}
        </span>
      )}
    </label>
  )
}

export function TitleSetupPage() {
  const navigate = useNavigate()
  const currentUser = useCurrentUser()
  const organizationId = currentUser.data?.memberships[0]?.organization.id
  const createTitle = useCreateTitle(organizationId)

  const [name, setName] = useState('')
  const [releaseDate, setReleaseDate] = useState('')
  const [milestones, setMilestones] = useState<MilestoneDraft[]>([])
  const [aliases, setAliases] = useState('')
  const [hashtags, setHashtags] = useState('')
  const [leadCast, setLeadCast] = useState('')
  const [directors, setDirectors] = useState('')
  const [musicDirectors, setMusicDirectors] = useState('')
  const [posterUrl, setPosterUrl] = useState('')

  if (currentUser.isPending) return <LoadingState label="Loading your workspace…" />
  if (currentUser.isError) return <ErrorState error={currentUser.error} />

  const anchors = {
    leadCast: parseTermList(leadCast),
    directors: parseTermList(directors),
    musicDirectors: parseTermList(musicDirectors),
  }
  const isCollectable = isNameCollectable(name, anchors)
  const needsAnchor = name.trim().length > 0 && !isCollectable
  const isSubmittable =
    isCollectable && Boolean(releaseDate) && !createTitle.isPending && Boolean(organizationId)

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!isSubmittable) return

    createTitle.mutate(
      {
        name: name.trim(),
        release_date: releaseDate,
        milestones: completedMilestones(milestones),
        aliases: parseTermList(aliases),
        hashtags: parseTermList(hashtags),
        lead_cast: anchors.leadCast,
        directors: anchors.directors,
        music_directors: anchors.musicDirectors,
        poster_url: posterUrl.trim() || null,
      },
      { onSuccess: () => void navigate('/', { replace: true }) },
    )
  }

  return (
    <section className="mx-auto max-w-2xl">
      <h1 className="text-xl font-semibold tracking-tight">Add a title</h1>
      <p className="text-ink-600 mt-1 text-sm">
        Everything you enter here becomes one identity set. Collection queries the whole set rather
        than the name on its own, which is what keeps a film apart from its namesakes.
      </p>

      <form
        onSubmit={handleSubmit}
        className="border-ink-200 mt-6 space-y-4 rounded-lg border bg-white p-5"
      >
        <label className="block">
          <span className="text-ink-600 block text-xs font-medium">Title name</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Vaaranam Aayiram"
            autoFocus
            className="border-ink-200 focus:border-brand-500 mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none"
          />
        </label>

        {/* Stated before submission, not raised as an error after it. */}
        <p
          className={
            needsAnchor
              ? 'border-ink-200 bg-ink-50 text-ink-900 rounded-md border px-3 py-2 text-xs'
              : 'text-ink-400 text-xs'
          }
        >
          A name shorter than {MIN_UNANCHORED_NAME_LENGTH} characters needs at least one anchor term
          — a cast or crew name — before it can be collected. A hashtag is not enough, since it can
          be as generic as the name.
          {needsAnchor && ' Add a cast, director, or music director name to continue.'}
        </p>

        <label className="block">
          <span className="text-ink-600 block text-xs font-medium">Release date</span>
          <input
            type="date"
            value={releaseDate}
            onChange={(event) => setReleaseDate(event.target.value)}
            required
            className="border-ink-200 focus:border-brand-500 mt-1 rounded-md border px-3 py-2 text-sm outline-none"
          />
          <span className="text-ink-400 mt-1 block text-xs">
            Required. Every chart splits before and after this date, so it is what lets you tell a
            spike you caused from one the audience did. You can move it later without losing
            anything already collected.
          </span>
        </label>

        <MilestoneEditor drafts={milestones} onChange={setMilestones} />

        <TermField
          label="Alternate names"
          hint="Comma-separated. Transliterations, working titles, common misspellings."
          value={aliases}
          onChange={setAliases}
          placeholder="Ninety Six, 96 the film"
        />

        <TermField
          label="Official hashtags"
          hint="Comma-separated. The # is optional and case does not matter."
          value={hashtags}
          onChange={setHashtags}
          placeholder="#96Movie, #96TheFilm"
        />

        <TermField
          label="Lead cast"
          hint="Comma-separated. Anchors the query."
          value={leadCast}
          onChange={setLeadCast}
          placeholder="Vijay Sethupathi, Trisha"
        />

        <TermField
          label="Director"
          hint="Comma-separated. Anchors the query."
          value={directors}
          onChange={setDirectors}
          placeholder="C. Prem Kumar"
        />

        <TermField
          label="Music director"
          hint="Comma-separated. Anchors the query."
          value={musicDirectors}
          onChange={setMusicDirectors}
          placeholder="Govind Vasantha"
        />

        <label className="block">
          <span className="text-ink-600 block text-xs font-medium">Poster URL</span>
          <input
            value={posterUrl}
            onChange={(event) => setPosterUrl(event.target.value)}
            placeholder="https://…"
            className="border-ink-200 focus:border-brand-500 mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none"
          />
          <span className="text-ink-400 mt-1 block text-xs">
            Optional. Reused as the title's identity on dashboards.
          </span>
        </label>

        <button
          type="submit"
          disabled={!isSubmittable}
          className="bg-brand-500 hover:bg-brand-600 w-full rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
        >
          {createTitle.isPending ? 'Saving…' : 'Save title'}
        </button>

        {createTitle.isError && <ErrorState error={createTitle.error} />}
      </form>
    </section>
  )
}
