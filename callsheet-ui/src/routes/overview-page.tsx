import { describeSegments, useSelectedAccountTypes } from '@/stores/segment-store'

export function OverviewPage() {
  const selectedAccountTypes = useSelectedAccountTypes()

  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">Social Intelligence Control Centre</h1>
      <p className="text-ink-600 mt-2 max-w-2xl text-sm">
        Scaffold is up. The Organizations screen is a working end-to-end slice — React Query calls
        the FastAPI backend through the Vite dev proxy. Title and Artist dashboards come next.
      </p>

      <div className="border-ink-200 mt-6 rounded-lg border bg-white p-4">
        <p className="text-ink-400 text-xs">Active segment</p>
        <p className="mt-1 text-sm font-medium">{describeSegments(selectedAccountTypes)}</p>
        <p className="text-ink-400 mt-2 text-xs">
          Every aggregate on every screen carries this label. It persists across navigation and
          reloads, and defaults to organic-only.
        </p>
      </div>
    </section>
  )
}
