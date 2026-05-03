/**
 * Top-nav filter strip — date range + group + TLP.
 *
 * Three filter dimensions, locked in plan D5:
 *  - **Date range**: working. Two `<input type="date">`. ISO yyyy-mm-dd
 *    output flows verbatim to the BE `date_from` / `date_to` query
 *    params.
 *  - **Group filter**: working. Multi-select dropdown over a
 *    hardcoded `FILTER_GROUP_OPTIONS`. The live-fetched groups
 *    endpoint is a follow-up — until the BE ships `/api/v1/groups`
 *    (PR #13+), this small list is enough to exercise the
 *    `group_id[]` repeatable param contract end-to-end.
 *  - **TLP filter**: UI-ONLY. Three checkboxes (WHITE/GREEN/AMBER —
 *    RED is workflow-only, not analyst-displayed). State lands in
 *    the store and renders the chip selection, but the
 *    store→payload transform (`lib/dashboardFilters.ts`) drops it
 *    so it never appears on the wire. See store + transform
 *    docstrings for the rationale (PR #11 D4 deferred TLP RLS).
 *
 * Mount point: Shell topbar (`layout/Shell.tsx`). Visible whenever
 * the Shell renders, which is exclusively under RouteGate's
 * authenticated branch — so no auth conditional is needed here.
 *
 * Token discipline (D4): every color goes through a semantic class
 * — bg-surface, text-ink, border-border-card. Surface-token regex
 * test in `__tests__/FilterBar.test.tsx` pins the discipline.
 */

import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { Check, ChevronDown, RotateCcw } from 'lucide-react'

import { cn } from '../lib/utils'
import { TLP_LEVELS, useFilterStore, type TlpLevel } from '../stores/filters'

export interface FilterGroupOption {
  readonly id: number
  readonly name: string
}

/**
 * Hardcoded for PR #12. Group F (PR #13+) replaces this with a live
 * fetch from a `/api/v1/groups` endpoint when that ships. IDs match
 * the seed-migration ordering documented in
 * `services/etl/migrations/` for predictable manual smoke-testing.
 */
export const FILTER_GROUP_OPTIONS: readonly FilterGroupOption[] = [
  { id: 1, name: 'Lazarus Group' },
  { id: 2, name: 'Kimsuky' },
  { id: 3, name: 'APT37' },
  { id: 4, name: 'APT38' },
  { id: 5, name: 'Andariel' },
] as const

const TLP_LABELS: Record<TlpLevel, string> = {
  WHITE: 'TLP:WHITE',
  GREEN: 'TLP:GREEN',
  AMBER: 'TLP:AMBER',
}

// Ferrari L2 form-input vocabulary (DESIGN.md §Forms text-input-on-dark):
// 4px corners (rounded-input), bg-app (canvas), 1px hairline border.
// h-8 is preserved for the inline filter strip — DESIGN.md spec
// height (48px) applies to standalone inputs like LoginPage; inline
// strip controls keep the existing compact density.
const inputClass = cn(
  'h-8 rounded-input border border-border-card bg-app px-2 text-xs text-ink',
  'focus:outline-none focus:ring-2 focus:ring-ring',
)

// Ferrari L2 button vocabulary (DESIGN.md §Buttons button-tertiary-text):
// sharp 0px corners (rounded-none), uppercase + tracking-cta + font-cta.
// Tertiary-text variant chosen because filter strip controls are not
// primary CTAs — Rosso Corsa is reserved per plan §0.1 invariant 3.
const buttonClass = cn(
  'flex h-8 items-center gap-2 rounded-none border border-border-card bg-app px-3 text-xs font-cta uppercase tracking-cta text-ink',
  'hover:border-signal focus:outline-none focus:ring-2 focus:ring-ring',
)

export function FilterBar(): JSX.Element {
  const {
    dateFrom,
    dateTo,
    groupIds,
    tlpLevels,
    setDateRange,
    toggleGroupId,
    toggleTlpLevel,
    clear,
  } = useFilterStore()

  const groupSummary =
    groupIds.length === 0 ? 'All groups' : `${groupIds.length} selected`

  return (
    <div
      data-testid="filter-bar"
      className={cn(
        'flex flex-wrap items-end gap-3 border-t border-border-card bg-surface px-6 py-3 text-ink',
      )}
    >
      <DateRange
        from={dateFrom}
        to={dateTo}
        onChange={(nextFrom, nextTo) => setDateRange(nextFrom, nextTo)}
      />

      <GroupSelect
        summary={groupSummary}
        selectedIds={groupIds}
        onToggle={toggleGroupId}
      />

      <TlpSelect selected={tlpLevels} onToggle={toggleTlpLevel} />

      <div className="ml-auto">
        <button
          type="button"
          data-testid="filter-clear"
          onClick={clear}
          className={cn(buttonClass, 'gap-1 text-ink-muted hover:text-ink')}
        >
          <RotateCcw aria-hidden className="h-3 w-3" />
          Clear
        </button>
      </div>
    </div>
  )
}

interface DateRangeProps {
  from: string | null
  to: string | null
  onChange: (from: string | null, to: string | null) => void
}

function DateRange({ from, to, onChange }: DateRangeProps): JSX.Element {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] font-cta uppercase tracking-nav text-ink-subtle">
        Date range
      </span>
      <div className="flex items-center gap-2">
        <input
          type="date"
          aria-label="Date from"
          data-testid="filter-date-from"
          value={from ?? ''}
          onChange={(e) => onChange(e.target.value || null, to)}
          className={inputClass}
        />
        <span aria-hidden className="text-ink-subtle">
          –
        </span>
        <input
          type="date"
          aria-label="Date to"
          data-testid="filter-date-to"
          value={to ?? ''}
          onChange={(e) => onChange(from, e.target.value || null)}
          className={inputClass}
        />
      </div>
    </div>
  )
}

interface GroupSelectProps {
  summary: string
  selectedIds: readonly number[]
  onToggle: (id: number) => void
}

function GroupSelect({ summary, selectedIds, onToggle }: GroupSelectProps): JSX.Element {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] font-cta uppercase tracking-nav text-ink-subtle">
        Groups
      </span>
      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <button
            type="button"
            data-testid="filter-group-trigger"
            className={buttonClass}
          >
            {summary}
            <ChevronDown aria-hidden className="h-3 w-3" />
          </button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content
            data-testid="filter-group-menu"
            className={cn(
              'z-50 min-w-[14rem] rounded-none border border-border-card bg-surface p-1 text-xs text-ink shadow-lg',
            )}
            sideOffset={4}
            align="start"
          >
            {FILTER_GROUP_OPTIONS.map((option) => {
              const checked = selectedIds.includes(option.id)
              return (
                <DropdownMenu.CheckboxItem
                  key={option.id}
                  data-testid={`filter-group-option-${option.id}`}
                  checked={checked}
                  onSelect={(event) => {
                    // Keep the menu open while toggling — analysts
                    // typically pick multiple groups in one pass.
                    event.preventDefault()
                    onToggle(option.id)
                  }}
                  className={cn(
                    'flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 outline-none',
                    'focus:bg-app data-[highlighted]:bg-app',
                  )}
                >
                  <span className="flex h-3 w-3 items-center justify-center">
                    {checked ? <Check aria-hidden className="h-3 w-3 text-signal" /> : null}
                  </span>
                  {option.name}
                </DropdownMenu.CheckboxItem>
              )
            })}
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
    </div>
  )
}

interface TlpSelectProps {
  selected: readonly TlpLevel[]
  onToggle: (level: TlpLevel) => void
}

function TlpSelect({ selected, onToggle }: TlpSelectProps): JSX.Element {
  return (
    <fieldset
      data-testid="filter-tlp"
      className="flex flex-col gap-1 border-0 p-0"
    >
      <legend className="text-[10px] font-cta uppercase tracking-nav text-ink-subtle">
        TLP{' '}
        <span className="font-normal normal-case text-ink-subtle">
          (UI-only)
        </span>
      </legend>
      <div className="flex h-8 items-center gap-3 rounded border border-border-card bg-app px-3">
        {TLP_LEVELS.map((level) => {
          const checked = selected.includes(level)
          return (
            <label
              key={level}
              className="flex cursor-pointer items-center gap-1 text-xs text-ink"
            >
              <input
                type="checkbox"
                data-testid={`filter-tlp-${level}`}
                checked={checked}
                onChange={() => onToggle(level)}
                className="h-3 w-3 accent-signal"
              />
              {TLP_LABELS[level]}
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}
