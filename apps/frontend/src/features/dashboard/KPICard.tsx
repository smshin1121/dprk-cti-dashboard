/**
 * Single KPI tile. Four render states, plan D11 locked:
 *
 *  - `loading` — shimmer skeleton, aria-busy=true. No value is ever
 *    rendered, so screen-readers announce "busy" rather than a stale
 *    number from a previous view.
 *  - `error` — inline error affordance. Retry button is OPTIONAL
 *    (`onRetry` prop) — when the strip shares a single retry, only
 *    the first card carries the button and the others render the
 *    error message only.
 *  - `empty` — placeholder dash (—). Used when the query succeeded
 *    but this specific slot has no data (e.g., `top_groups: []`
 *    under the current filter).
 *  - `populated` — label + formatted value + optional subtext.
 *
 *  All colors go through Ferrari semantic tokens (Ferrari L1).
 *  Per-section light editorial bands flip surface tokens via
 *  `editorial-band-light` without component-side changes.
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

export function KPICard({
  label,
  value,
  subtext,
  state,
  onRetry,
}: KPICardProps): JSX.Element {
  const isLoading = state === 'loading'
  return (
    <div
      data-testid="kpi-card"
      aria-busy={isLoading ? 'true' : 'false'}
      className={cn(
        'flex min-w-[10rem] flex-1 flex-col gap-1 rounded-none border border-border-card bg-surface p-4',
      )}
    >
      <span className="text-[10px] font-cta uppercase tracking-caption text-ink-subtle">
        {label}
      </span>
      {isLoading ? <LoadingBody /> : null}
      {state === 'error' ? <ErrorBody onRetry={onRetry} /> : null}
      {state === 'empty' ? <EmptyBody /> : null}
      {state === 'populated' ? (
        <PopulatedBody value={value} subtext={subtext} />
      ) : null}
    </div>
  )
}

function LoadingBody(): JSX.Element {
  return (
    <div data-testid="kpi-card-skeleton" className="flex flex-col gap-2">
      <div className="h-6 w-24 animate-pulse rounded bg-border-card" />
      <div className="h-3 w-16 animate-pulse rounded bg-border-card" />
    </div>
  )
}

function EmptyBody(): JSX.Element {
  return (
    <>
      <span
        data-testid="kpi-card-value"
        className="text-2xl font-semibold text-ink-muted"
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
        className="text-2xl font-semibold text-ink"
      >
        {formatValue(value)}
      </span>
      {subtext ? (
        <span className="text-xs text-ink-subtle">{subtext}</span>
      ) : null}
    </>
  )
}
