/**
 * Single KPI tile — DASHBOARD COMPACT VARIANT (PR 2.5).
 *
 * Replaces the prior 80px Ferrari L3 spec-cell hero treatment with
 * the dashboard-scoped compact variant defined in DESIGN.md
 * `## Dashboard KPI Compact Variant`. The global `## Spec & Race
 * Surfaces` lock from PR #31 is NOT revised — race-position-cell
 * and non-dashboard spec-cell consumers continue to use the 80px
 * `{typography.number-display}` token. This component is consumed
 * only by KPIStrip on `/dashboard`.
 *
 * Render states (unchanged contract):
 *   - `loading` — skeleton at the new `text-3xl` footprint (NOT 80px).
 *   - `error` — small card chrome (status callout — only state with
 *               border + bg-surface).
 *   - `empty` — placeholder `—` at `text-3xl` to keep the cell
 *               footprint stable when data lands.
 *   - `populated` — caption label + `text-3xl` value + optional
 *                   subtext + optional delta + optional sparkline.
 *
 * Compact variant additions (PR 2.5 L4 + L5):
 *   - `delta?: KpiDelta | null` — direction-derived sign + color.
 *     Positive → status-ok; negative → status-warn; null → slot
 *     omitted entirely. Same reserved-slot text-only discipline that
 *     governs `actor-network-graph` and `alerts-rail-section`.
 *   - `sparkline?: readonly number[] | null` — inline SVG path,
 *     ~60×24, single 1px stroke at `colors.muted-soft`. Series < 2
 *     points → slot omitted.
 *
 * Aggregate-card treatment (PR 2.5 L3):
 *   - When `value` is a string (Top Group / Top Motivation / Top
 *     Year primary label), use `text-lg` instead of `text-3xl`.
 *     Short categorical strings at 80px would have been typography
 *     misuse even within the locked spec-cell pattern.
 */

import { AlertTriangle, RotateCcw } from 'lucide-react'

import { cn } from '../../lib/utils'
import type { KpiDelta } from './kpiDeltaUtils'
import { buildSparklinePath } from './kpiDeltaUtils'

export type KPICardState = 'loading' | 'error' | 'empty' | 'populated'

export interface KPICardProps {
  label: string
  value?: string | number
  subtext?: string
  state: KPICardState
  onRetry?: () => void
  /** Optional YoY (or other) percent delta. null collapses the slot. */
  delta?: KpiDelta | null
  /** Optional series for sparkline. < 2 points collapses the slot. */
  sparkline?: readonly number[] | null
}

const numberFormat = new Intl.NumberFormat('en-US')

function formatValue(value: string | number | undefined): string {
  if (value == null) return '—'
  if (typeof value === 'number') return numberFormat.format(value)
  return value
}

// Compact-variant value typography. Scalar numbers use text-3xl
// (~30px); aggregate strings use text-lg. Subtext stays small.
const COMPACT_SCALAR_VALUE_CLASS = cn(
  'text-3xl font-cta leading-tight',
)
const COMPACT_AGGREGATE_VALUE_CLASS = cn(
  'text-lg font-cta leading-tight',
)

function isAggregateString(value: string | number | undefined): boolean {
  // Aggregate cards (Top Group / Top Motivation / Top Year primary
  // label) pass a string. Scalar cards (Total Reports / Incidents /
  // Actors) pass a number. Top Year passes a string-coerced year
  // ("2024") — that's still a number-ish display so we keep it
  // text-3xl. Distinguish by parseability.
  if (typeof value !== 'string') return false
  // String of digits only → display as a numeric (text-3xl).
  if (/^[0-9]+$/.test(value)) return false
  return true
}

export function KPICard({
  label,
  value,
  subtext,
  state,
  onRetry,
  delta,
  sparkline,
}: KPICardProps): JSX.Element {
  const isLoading = state === 'loading'
  // Error keeps small card chrome (status callout). All other states
  // are transparent floating cells per the compact variant.
  const isError = state === 'error'
  const valueClass = isAggregateString(value)
    ? COMPACT_AGGREGATE_VALUE_CLASS
    : COMPACT_SCALAR_VALUE_CLASS

  return (
    <div
      data-testid="kpi-card"
      aria-busy={isLoading ? 'true' : 'false'}
      className={cn(
        'flex min-w-[8rem] flex-col gap-1',
        isError &&
          'rounded-none border border-border-card bg-surface p-4',
      )}
    >
      <span className="text-[10px] font-cta uppercase tracking-caption text-ink-subtle">
        {label}
      </span>
      {isLoading ? <LoadingBody /> : null}
      {isError ? <ErrorBody onRetry={onRetry} /> : null}
      {state === 'empty' ? <EmptyBody valueClass={COMPACT_SCALAR_VALUE_CLASS} /> : null}
      {state === 'populated' ? (
        <PopulatedBody
          value={value}
          subtext={subtext}
          delta={delta}
          sparkline={sparkline}
          valueClass={valueClass}
        />
      ) : null}
    </div>
  )
}

function LoadingBody(): JSX.Element {
  // Skeleton at the compact text-3xl footprint, NOT 80px. Keeps the
  // cell from shifting when the populated value lands.
  return (
    <div data-testid="kpi-card-skeleton" className="flex flex-col gap-1.5">
      <div className="h-7 w-20 animate-pulse rounded-none bg-border-card" />
      <div className="h-3 w-12 animate-pulse rounded-none bg-border-card" />
    </div>
  )
}

interface EmptyBodyProps {
  valueClass: string
}

function EmptyBody({ valueClass }: EmptyBodyProps): JSX.Element {
  return (
    <>
      <span
        data-testid="kpi-card-value"
        className={cn(valueClass, 'text-ink-muted')}
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
  delta: KpiDelta | null | undefined
  sparkline: readonly number[] | null | undefined
  valueClass: string
}

function PopulatedBody({
  value,
  subtext,
  delta,
  sparkline,
  valueClass,
}: PopulatedBodyProps): JSX.Element {
  return (
    <>
      <div className="flex items-baseline gap-3">
        <span
          data-testid="kpi-card-value"
          className={cn(valueClass, 'text-ink')}
        >
          {formatValue(value)}
        </span>
        {sparkline && sparkline.length >= 2 ? (
          <KpiSparkline series={sparkline} />
        ) : null}
      </div>
      {subtext ? (
        <span className="text-xs text-ink-subtle">{subtext}</span>
      ) : null}
      {delta ? <KpiDeltaBadge delta={delta} /> : null}
    </>
  )
}

interface KpiDeltaBadgeProps {
  delta: KpiDelta
}

function KpiDeltaBadge({ delta }: KpiDeltaBadgeProps): JSX.Element {
  const sign = delta.value > 0 ? '+' : delta.value < 0 ? '' : ''
  const directionClass =
    delta.value > 0
      ? 'text-status-ok'
      : delta.value < 0
        ? 'text-status-warn'
        : 'text-ink-subtle'
  return (
    <span
      data-testid="kpi-card-delta"
      className={cn(
        'text-xs font-cta tracking-caption',
        directionClass,
      )}
    >
      {sign}
      {delta.value.toFixed(1)}%
    </span>
  )
}

interface KpiSparklineProps {
  series: readonly number[]
}

function KpiSparkline({ series }: KpiSparklineProps): JSX.Element | null {
  const path = buildSparklinePath(series, 60, 24)
  if (path === null) return null
  return (
    <span
      data-testid="kpi-card-sparkline"
      aria-hidden
      className="inline-flex"
    >
      <svg
        width="60"
        height="24"
        viewBox="0 0 60 24"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path
          d={path}
          fill="none"
          stroke="currentColor"
          strokeWidth="1"
          className="text-ink-subtle"
        />
      </svg>
    </span>
  )
}
