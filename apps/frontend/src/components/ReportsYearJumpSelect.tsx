/**
 * Year quick-jump for /reports — sets the global date range filter
 * to the selected year's full span, or clears it for "All years".
 *
 * Discoverability companion to FilterBar's date pickers in the
 * Shell. The Shell-level FilterBar is the canonical fine-grained
 * date filter; this select is a one-click shortcut for the most
 * common timeline-navigation gesture ("show me 2024 reports") so
 * timeline-mode users don't have to find the FilterBar first.
 *
 * Year list spans `REPORT_DATA_START_YEAR` (2009 — earliest
 * report in the workbook) through the current calendar year. Any
 * non-year-aligned ranges from the FilterBar render as "Custom
 * range" so the UI does not claim the list is unfiltered.
 */

import { useFilterStore } from '../stores/filters'

const REPORT_DATA_START_YEAR = 2009
const CUSTOM_RANGE_VALUE = 'custom'

function listReportYearsDesc(): readonly string[] {
  const current = new Date().getFullYear()
  const years: string[] = []
  for (let y = current; y >= REPORT_DATA_START_YEAR; y--) {
    years.push(String(y))
  }
  return years
}

/** Detect whether the active date range exactly matches one full
 * calendar year — if so, that year is the "current" select value;
 * null bounds mean "All years"; all other non-year-aligned ranges
 * render as "Custom range". */
function detectActiveYear(
  dateFrom: string | null,
  dateTo: string | null,
): string {
  if (dateFrom == null && dateTo == null) return ''
  if (dateFrom == null || dateTo == null) return CUSTOM_RANGE_VALUE
  if (!/^\d{4}-01-01$/.test(dateFrom)) return CUSTOM_RANGE_VALUE
  if (!/^\d{4}-12-31$/.test(dateTo)) return CUSTOM_RANGE_VALUE
  if (dateFrom.slice(0, 4) !== dateTo.slice(0, 4)) {
    return CUSTOM_RANGE_VALUE
  }
  const year = dateFrom.slice(0, 4)
  const numericYear = Number(year)
  if (
    numericYear < REPORT_DATA_START_YEAR ||
    numericYear > new Date().getFullYear()
  ) {
    return CUSTOM_RANGE_VALUE
  }
  return year
}

export function ReportsYearJumpSelect(): JSX.Element {
  const dateFrom = useFilterStore((s) => s.dateFrom)
  const dateTo = useFilterStore((s) => s.dateTo)
  const setDateRange = useFilterStore((s) => s.setDateRange)
  const years = listReportYearsDesc()
  const value = detectActiveYear(dateFrom, dateTo)

  return (
    <label className="flex items-center gap-2 text-xs text-ink-muted">
      <span>Year</span>
      <select
        data-testid="reports-year-jump"
        aria-label="Jump to year"
        value={value}
        onChange={(e) => {
          const y = e.target.value
          if (y === '') {
            setDateRange(null, null)
          } else if (y === CUSTOM_RANGE_VALUE) {
            return
          } else {
            setDateRange(`${y}-01-01`, `${y}-12-31`)
          }
        }}
        className="rounded-md border border-border-card bg-surface px-2 py-1 text-ink hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-ring"
      >
        <option value="">All years</option>
        {value === CUSTOM_RANGE_VALUE ? (
          <option value={CUSTOM_RANGE_VALUE}>Custom range</option>
        ) : null}
        {years.map((y) => (
          <option key={y} value={y}>
            {y}
          </option>
        ))}
      </select>
    </label>
  )
}
