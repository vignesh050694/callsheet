import { NavLink, Outlet } from 'react-router-dom'

import { SegmentSelector } from '@/components/layout/segment-selector'
import { useHealth } from '@/hooks/use-health'

const NAV_ITEMS = [
  { to: '/', label: 'Workspace', end: true },
  { to: '/overview', label: 'Overview', end: false },
  { to: '/members', label: 'Members', end: false },
  { to: '/organizations', label: 'Organizations', end: false },
]

function BackendStatus() {
  const { data, isPending, isError } = useHealth()

  if (isPending) return <span className="text-ink-400 text-xs">checking API…</span>
  if (isError) return <span className="text-xs text-red-600">API unreachable</span>

  return (
    <span className="text-ink-400 text-xs">
      API {data.version} · {data.environment}
    </span>
  )
}

export function AppLayout() {
  return (
    <div className="flex min-h-full flex-col">
      <header className="border-ink-200 border-b bg-white">
        <div className="mx-auto flex max-w-5xl items-center gap-8 px-6 py-4">
          <span className="text-base font-semibold tracking-tight">Callsheet</span>
          <nav className="flex gap-4">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  isActive
                    ? 'text-brand-600 text-sm font-medium'
                    : 'text-ink-600 hover:text-ink-900 text-sm'
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto">
            <BackendStatus />
          </div>
        </div>

        {/* Global chrome: visible on every screen, so no aggregate is read without its segment. */}
        <div className="border-ink-200 bg-ink-50 border-t">
          <div className="mx-auto max-w-5xl px-6 py-2">
            <SegmentSelector />
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-8">
        <Outlet />
      </main>
    </div>
  )
}
