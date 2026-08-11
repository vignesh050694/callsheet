# Callsheet UI

React + Vite frontend for the Agentic Social Media Control Centre.

## Stack

- Vite 8 + React 19 + TypeScript (strict)
- Tailwind CSS v4 (`@tailwindcss/vite` — no `tailwind.config.js`; theme tokens live in `src/index.css`)
- React Router 7
- TanStack Query 5 for all server state
- Zustand 5 for client state
- oxlint (the Vite template's linter) + Prettier

## Getting started

```bash
cp .env.example .env.local
npm install
npm run dev          # http://localhost:5173
```

Start the backend too (`cd ../callsheet && make dev`). Requests to `/api` are proxied to `http://localhost:8000`, so the browser sees one origin and there is no CORS preflight in development.

Set `VITE_PILOT_USER_ID` in `.env.local` to the output of `make seed-user email=... name="..."` from the backend, or leave it blank and set it in localStorage at runtime for quick testing.

## Commands

| Command             | What it does                               |
| ------------------- | ------------------------------------------ |
| `npm run dev`       | Dev server with HMR on :5173               |
| `npm run build`     | Typecheck then production build to `dist/` |
| `npm run preview`   | Serve the production build                 |
| `npm run typecheck` | `tsc -b`                                   |
| `npm run lint`      | oxlint                                     |
| `npm run format`    | Prettier write                             |
| `npm run check`     | lint + typecheck + format check            |

## Layout

```
src/
  main.tsx                    providers: QueryClient, Router
  App.tsx                     route table
  routes/                     one file per page
    onboarding-page.tsx       new user sets studio name + org type (E01-S01)
    titles-page.tsx           empty state for title list (E02 upcoming)
  components/
    layout/app-layout.tsx     shell: nav + backend status
    layout/workspace-gate.tsx onboarding or titles, by membership state
    ui/                       small shared presentational pieces
  hooks/                      one file per resource, wrapping TanStack Query
  stores/                     one file per Zustand store (client state)
  lib/
    api-client.ts             fetch wrapper, ApiError, base URL
    query-client.ts           cache defaults and retry policy
    session.ts                reads pilot user id from env or localStorage
  types/api.ts                types mirroring the backend Pydantic schemas
  index.css                   Tailwind import + theme tokens
```

### Conventions

- **Components never call `fetch` directly.** They use a hook from `src/hooks/`, which uses `apiClient`. That keeps cache keys and invalidation in one place per resource.
- **`@/` is an alias for `src/`**, configured in both `vite.config.ts` and `tsconfig.app.json` — keep the two in sync.
- **Server errors** arrive as `ApiError` with `status`, `code`, and `requestId`. The request id matches the backend's `X-Request-ID` log field, so a UI error can be traced straight to a backend log line.
- **Types in `src/types/api.ts` are hand-written** to match `callsheet/app/schemas/`. If the backend contract changes, update them together. (The backend publishes OpenAPI at `/openapi.json` if you later want to generate these.)
- **Env vars must be `VITE_`-prefixed** to reach the bundle — and anything that reaches the bundle is public. No secrets.

## State management

The split is the whole point — get it wrong and the two libraries fight:

| Kind of state                                                      | Owner                         | Examples                                                 |
| ------------------------------------------------------------------ | ----------------------------- | -------------------------------------------------------- |
| **Server state** — anything the backend is the source of truth for | TanStack Query (`src/hooks/`) | organizations, mentions, aggregates                      |
| **Client state** — the user's current lens on that data            | Zustand (`src/stores/`)       | selected account-type segment, filters, drafts, UI prefs |

Never mirror fetched data into a Zustand store. If it came from the API, it belongs in a query, and the store holds only the inputs (filters, selection) that feed the query key.

### Store conventions

`src/stores/segment-store.ts` is the reference implementation. Follow its shape:

1. **One store per file**, named `<domain>-store.ts`.
2. **Actions live in a nested `actions` object**, not spread across the state root. `useSegmentActions()` returns an object with a stable identity, so consuming it never triggers a re-render and it is safe in dependency arrays.
3. **Export atomic selector hooks; never subscribe to the whole store.** Zustand v5 compares with `Object.is` and does no shallow check, so `useSegmentStore()` bare re-renders a component on every unrelated change. Components import `useSelectedAccountTypes()`, not the store.
4. **`persist` for anything that should survive a reload**, with a namespaced `name` (`callsheet.*`), an explicit `version` for future migrations, and `partialize` to keep actions out of storage.
5. **`devtools` is enabled only in dev** (`enabled: import.meta.env.DEV`); every `set` passes an action name so the Redux DevTools timeline is readable.
6. **Encode invariants in the store, not in the component.** The segment store clamps an empty selection back to organic-only and keeps the selection in canonical order — a component cannot get it wrong, and query keys stay stable.
7. **Outside React**, read state with `useSegmentStore.getState()` (e.g. when building a query key or logging).

### The segment store specifically

Account-type segmentation is a product invariant, not a UI preference — see the `social-intel-ui-standards` skill in `.claude/skills/`. The selector is global chrome in the app shell, persists across navigation and reloads, and defaults to **organic-only**, because that is the number people believe they are reading. Every aggregate must display which segments it covers; use `describeSegments()` for that label.

### Routing and the workspace gate

The index route (`/`) renders `WorkspaceGate`, which queries `GET /api/v1/me` to read the user's memberships. If empty (first-time user), it renders the onboarding screen; otherwise, the titles list. The Overview page lives at `/overview`; `/organizations` is unchanged. Pilot user identity flows from `session.ts`, which reads `VITE_PILOT_USER_ID` from env or localStorage and is sent as `X-User-Id` on every request.

## Adding a page

1. Add types to `src/types/api.ts`
2. Add `src/hooks/use-<resource>.ts` with the query keys and hooks
3. Add `src/routes/<name>-page.tsx`
4. Register the route in `src/App.tsx` and, if it needs nav, in `app-layout.tsx`
5. If the screen shows an aggregate, read the segment from `useSelectedAccountTypes()`, include it in the query key, and label the number with `describeSegments()`

`routes/organizations-page.tsx` + `hooks/use-organizations.ts` are the reference example, covering list, create, loading, empty, and error states.
