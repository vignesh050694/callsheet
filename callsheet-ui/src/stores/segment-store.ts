/**
 * Account-type segmentation — the platform's most load-bearing piece of client state.
 *
 * Per the UI standards (Invariant A) this selector is global chrome, not a per-screen
 * filter: it lives in the app shell, persists across navigation and reloads, and every
 * aggregate on every screen is computed against it. It defaults to organic-only, because
 * that is the number people believe they are reading when they look at sentiment.
 *
 * It lives in Zustand rather than TanStack Query because it is client state — a user's
 * current lens on the data, not data fetched from the server. Query keys read from it,
 * so changing the segment refetches aggregates.
 */

import { create } from 'zustand'
import { devtools, persist } from 'zustand/middleware'

export type AccountType = 'organic' | 'trade' | 'owned_media' | 'promotional'

export const ACCOUNT_TYPES: readonly AccountType[] = [
  'organic',
  'trade',
  'owned_media',
  'promotional',
]

export const ACCOUNT_TYPE_LABELS: Record<AccountType, string> = {
  organic: 'Organic audience',
  trade: 'Trade & trackers',
  owned_media: 'Owned media',
  promotional: 'Promotional',
}

/** What a screen shows when it has to label which segments a number covers. */
export const ORGANIC_ONLY: readonly AccountType[] = ['organic']

const PERSIST_KEY = 'callsheet.segment'
const PERSIST_VERSION = 1

interface SegmentActions {
  toggleAccountType: (accountType: AccountType) => void
  setAccountTypes: (accountTypes: AccountType[]) => void
  resetToOrganicOnly: () => void
}

interface SegmentState {
  selectedAccountTypes: AccountType[]
  actions: SegmentActions
}

/**
 * An aggregate over zero segments has no meaning, and an empty selector reads as
 * "everything" to most people — the opposite of what it would compute. Deselecting the
 * last segment falls back to organic-only rather than to nothing.
 */
function withNonEmptyFallback(accountTypes: AccountType[]): AccountType[] {
  return accountTypes.length > 0 ? accountTypes : [...ORGANIC_ONLY]
}

/** Keeps persisted and in-memory order canonical, so query keys stay stable. */
function inCanonicalOrder(accountTypes: AccountType[]): AccountType[] {
  return ACCOUNT_TYPES.filter((accountType) => accountTypes.includes(accountType))
}

export const useSegmentStore = create<SegmentState>()(
  devtools(
    persist(
      (set) => ({
        selectedAccountTypes: [...ORGANIC_ONLY],

        actions: {
          toggleAccountType: (accountType) =>
            set(
              (state) => {
                const isSelected = state.selectedAccountTypes.includes(accountType)
                const next = isSelected
                  ? state.selectedAccountTypes.filter((item) => item !== accountType)
                  : [...state.selectedAccountTypes, accountType]

                return { selectedAccountTypes: inCanonicalOrder(withNonEmptyFallback(next)) }
              },
              undefined,
              'segment/toggleAccountType',
            ),

          setAccountTypes: (accountTypes) =>
            set(
              { selectedAccountTypes: inCanonicalOrder(withNonEmptyFallback(accountTypes)) },
              undefined,
              'segment/setAccountTypes',
            ),

          resetToOrganicOnly: () =>
            set(
              { selectedAccountTypes: [...ORGANIC_ONLY] },
              undefined,
              'segment/resetToOrganicOnly',
            ),
        },
      }),
      {
        name: PERSIST_KEY,
        version: PERSIST_VERSION,
        // Actions are behaviour, not state — persisting them would rehydrate stale closures.
        partialize: (state) => ({ selectedAccountTypes: state.selectedAccountTypes }),
      },
    ),
    { name: 'segment-store', enabled: import.meta.env.DEV },
  ),
)

/*
 * Atomic selector hooks.
 *
 * Zustand v5 compares with Object.is and does no shallow check, so a component that
 * subscribes to the whole store re-renders on every unrelated change. Components use the
 * hooks below and never call `useSegmentStore()` bare.
 */

export const useSelectedAccountTypes = () => useSegmentStore((state) => state.selectedAccountTypes)

/** Stable identity — safe in dependency arrays and never causes a re-render. */
export const useSegmentActions = () => useSegmentStore((state) => state.actions)

export const useIsOrganicOnly = () =>
  useSegmentStore(
    (state) =>
      state.selectedAccountTypes.length === 1 && state.selectedAccountTypes[0] === 'organic',
  )

/**
 * The label every aggregate carries so a number is never shown without its segment.
 * Read it outside React (query keys, logging) with `useSegmentStore.getState()`.
 */
export function describeSegments(accountTypes: readonly AccountType[]): string {
  if (accountTypes.length === ACCOUNT_TYPES.length) return 'All account types'
  return accountTypes.map((accountType) => ACCOUNT_TYPE_LABELS[accountType]).join(' + ')
}
