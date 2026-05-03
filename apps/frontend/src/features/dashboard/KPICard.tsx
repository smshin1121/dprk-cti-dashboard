/**
 * Single KPI tile. Four render states, plan D11 locked.
 *
 * Ferrari L3 retrofit (plan §5 spec-cell mapping):
 *   - Container: transparent (no bg-surface, no border, no card chrome)
 *     so the tile reads as a floating spec-cell on the page canvas
 *     per DESIGN.md §Spec & Race Surfaces.
 *   - Value: typography.number-display — 80px / 700 / 1.0 line-height
 *     / -1.6px tracking (text-[80px] font-cta leading-none
 *     tracking-number-display). Editorial confidence over card chrome.
 *   - Label: typography.caption-uppercase — 11px / 600 caption above
 *     the number callout.
 *   - Subtext: optional small caption under the number, retained from
 *     pre-Ferrari for the secondary text on aggregate KPIs (e.g.
 *     "12 reports" beneath "2024" for Top Year).
 *   - Error chrome remains a small card-style callout because errors
 *     are first-class status, not editorial spec-cells; retry button
 *     keeps the L2 button-tertiary-text vocabulary.
 *
 * State semantics unchanged:
 *   - `loading` — skeleton sized to the new 80px value column;
 *     aria-busy=true so screen readers announce busy.
 *   - `error` — inline error affordance with optional retry.
 *   - `empty` — placeholder dash (—) at number-display geometry.
 *   - `populated` — caption label + 80px value + optional subtext.
 */

import { AlertTriangle, RotateCcw } from 'lucide-react'

import { cn } from '../../lib/utils'

export type KPICardState = 'loading' | 'error' | 'empty' | 'populated'

export interface KPICardProps {
  label: string
  value?: string | number
  subtext?: string
  state: KPICardState
  onRetry?: () => void
}

const numberFormat = new Intl.NumberFormat('en-US')

function formatValue(value: string | number | undefined): string {
  if (value == null) return '—'
  if (typeof value === 'number') return numberFormat.format(value)
  return value
}

// Ferrari spec-cell value typography — number-display 80px / 700 /
// 1.0 line-height / -1.6px tracking. Shared between populated +
// empty states so the dash visually matches the number-display
// geometry.
const SPEC_CELL_VALUE_CLASS = cn(
  'text-[80px] font-cta leading-none tracking-number-display',
)

export function KPICard({
  label,
  value,
  subtext,
  state,
  onRetry,
}: KPICardProps): JSX.Element {
  const isLoading = state === 'loading'
  // Error state keeps the small card chrome — errors are first-class
  // status callouts, NOT editorial spec-cells. All other states are
  // transparent floating spec-cells per DESIGN.md.
  const isError = state === 'error'
  return (
    <div
      data-testid="kpi-card"
      aria-busy={isLoading ? 'true' : 'false'}
      className={cn(
        'flex min-w-[10rem] flex-1 flex-col gap-2',
        isError &&
          'rounded-none border border-border-card bg-surface p-4',
      )}
    >
      <span className="text-[10px] font-cta uppercase tracking-caption text-ink-subtle">
        {label}
      </span>
      {isLoading ? <LoadingBody /> : null}
      {isError ? <ErrorBody onRetry={onRetry} /> : null}
      {state === 'empty' ? <EmptyBody /> : null}
      {state === 'populated' ? (
        <PopulatedBody value={value} subtext={subtext} />
      ) : null}
    </div>
  )
}

function LoadingBody(): JSX.Element {
  // Skeleton sized to the spec-cell number-display footprint so the
  // layout doesn't reflow when the populated value lands.
  return (
    <div data-testid="kpi-card-skeleton" className="flex flex-col gap-2">
      <div className="h-[80px] w-full max-w-[160px] animate-pulse rounded-none bg-border-card" />
      <div className="h-3 w-16 animate-pulse rounded-none bg-border-card" />
    </div>
  )
}

function EmptyBody(): JSX.Element {
  return (
    <>
      <span
        data-testid="kpi-card-value"
        className={cn(SPEC_CELL_VALUE_CLASS, 'text-ink-muted')}
      >
        —
      </span>
      <span className="text-xs text-ink-subtle">No data for current filters</span>
    </>
  )
}

interface ErrorBodyProps {
  onRetry?: () => void
}

function ErrorBody({ onRetry }: ErrorBodyProps): JSX.Element {
  return (
    <div className="flex flex-col gap-2">
      <span
        data-testid="kpi-card-error-message"
        className="flex items-center gap-1 text-xs text-destructive"
      >
        <AlertTriangle aria-hidden className="h-3 w-3" />
        Failed to load
      </span>
      {onRetry ? (
        <button
          type="button"
          data-testid="kpi-card-retry"
          onClick={onRetry}
          className={cn(
            'flex items-center gap-1 self-start rounded-none border border-border-card bg-app px-2 py-1 text-xs font-cta uppercase tracking-cta text-ink',
            'hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-ring',
          )}
        >
          <RotateCcw aria-hidden className="h-3 w-3" />
          Retry
        </button>
      ) : null}
    </div>
  )
}

interface PopulatedBodyProps {
  value: string | number | undefined
  subtext: string | undefined
}

function PopulatedBody({ value, subtext }: PopulatedBodyProps): JSX.Element {
  return (
    <>
      <span
        data-testid="kpi-card-value"
        className={cn(SPEC_CELL_VALUE_CLASS, 'text-ink')}
      >
        {formatValue(value)}
      </span>
      {subtext ? (
        <span className="text-xs text-ink-subtle">{subtext}</span>
      ) : null}
    </>
  )
}
