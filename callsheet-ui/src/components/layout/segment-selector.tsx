/**
 * The global account-type selector (UI standards, Invariant A).
 *
 * Rendered once in the app shell so it is visible on every screen that shows a number,
 * rather than buried inside a single feed. Styling is deliberately greyscale (Invariant D)
 * — saturated colour is reserved for the sentiment scale, so chrome must not compete.
 */

import {
  ACCOUNT_TYPE_LABELS,
  ACCOUNT_TYPES,
  useIsOrganicOnly,
  useSegmentActions,
  useSelectedAccountTypes,
} from '@/stores/segment-store'

export function SegmentSelector() {
  const selectedAccountTypes = useSelectedAccountTypes()
  const { toggleAccountType, resetToOrganicOnly } = useSegmentActions()
  const isOrganicOnly = useIsOrganicOnly()

  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Account types">
      <span className="text-ink-400 text-xs">Segment</span>

      {ACCOUNT_TYPES.map((accountType) => {
        const isSelected = selectedAccountTypes.includes(accountType)
        return (
          <button
            key={accountType}
            type="button"
            aria-pressed={isSelected}
            onClick={() => toggleAccountType(accountType)}
            className={
              isSelected
                ? 'border-ink-900 bg-ink-900 rounded-full border px-3 py-1 text-xs font-medium text-white'
                : 'border-ink-200 text-ink-600 hover:border-ink-400 rounded-full border px-3 py-1 text-xs'
            }
          >
            {ACCOUNT_TYPE_LABELS[accountType]}
          </button>
        )
      })}

      {!isOrganicOnly && (
        <button
          type="button"
          onClick={resetToOrganicOnly}
          className="text-ink-400 hover:text-ink-900 text-xs underline underline-offset-2"
        >
          Reset to organic
        </button>
      )}
    </div>
  )
}
