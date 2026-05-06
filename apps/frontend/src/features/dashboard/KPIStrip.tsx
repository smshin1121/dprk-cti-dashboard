/**
 * Six-card KPI strip — DASHBOARD COMPACT VARIANT (PR 2.5).
 *
 * Layout: 6-cell grid per DESIGN.md `## Dashboard KPI Compact Variant`
 * (`grid grid-cols-3 lg:grid-cols-6 gap-4`). Replaces the previous
 * `flex flex-wrap gap-8 p-6` layout that the 80px hero typography
 * forced into irregular wrapping.
 *
 * Compact-variant additions (PR 2.5 L4 + L5):
 *   - Total Reports card receives a YoY delta computed client-side
 *     from `summary.reports_by_year` (via `computeYoyDelta`) and a
 *     sparkline series from the same source (via
 *     `extractSparklineSeries`).
 *   - All five other cards (Total Incidents, Total Actors, Top Year,
 *     Top Motivation, Top Group) render with delta + sparkline slots
 *     OMITTED — the BE summary doesn't expose a meaningful series for
 *     those, and inventing one is forbidden by the reserved-slot
 *     text-only discipline carried over from PR #33.
 *   - When `summary.reports_by_year` has fewer than 2 entries, even
 *     the Total Reports card omits delta + sparkline (graceful empty).
 *
 * Mapping unchanged (still 6 cards, same data sources):
 *   1. Total Reports        (scalar, +delta, +sparkline)
 *   2. Total Incidents      (scalar)
 *   3. Total Actors         (scalar)
 *   4. Top Year             (reports_by_year → max by count)
 *   5. Top Motivation       (incidents_by_motivation[0])
 *   6. Top Group            (top_groups[0])
 *
 * State propagation (plan D11 carryover):
 *   - Loading → all 6 cards show their own skeleton (six aria-busy).
 *   - Errored → all 6 cards show inline error; ONE retry button on
 *               the first card to prevent rage-click refetch storm.
 *   - Succeeded → scalars always populated (0 is "zero results", not
 *                 "no data"); aggregates fall back to `empty` when
 *                 their source array is empty.
 */

import type {
  DashboardMotivationCount,
  DashboardTopGroup,
  DashboardYearCount,
} from '../../lib/api/schemas'
import { KPICard, type KPICardState } from './KPICard'
import {
  computeYoyDelta,
  extractSparklineSeries,
  type KpiDelta,
} from './kpiDeltaUtils'
import { useDashboardSummary } from './useDashboardSummary'

function pickTopYear(
  entries: readonly DashboardYearCount[],
): DashboardYearCount | null {
  if (entries.length === 0) return null
  return entries.reduce((max, cur) => (cur.count > max.count ? cur : max))
}

function firstOrNull<T>(entries: readonly T[]): T | null {
  return entries.length > 0 ? entries[0] : null
}

export function KPIStrip(): JSX.Element {
  const query = useDashboardSummary()

  const stripState: 'loading' | 'error' | 'ready' = query.isLoading
    ? 'loading'
    : query.isError
      ? 'error'
      : 'ready'

  const commonState: KPICardState =
    stripState === 'loading' ? 'loading' : stripState === 'error' ? 'error' : 'populated'

  const data = stripState === 'ready' ? (query.data ?? null) : null
  const topYear = data ? pickTopYear(data.reports_by_year) : null
  const topMotivation: DashboardMotivationCount | null = data
    ? firstOrNull(data.incidents_by_motivation)
    : null
  const topGroup: DashboardTopGroup | null = data
    ? firstOrNull(data.top_groups)
    : null

  // Total Reports gets the compact-variant delta + sparkline. Every
  // other card has these omitted; the BE summary doesn't expose a
  // honest series for them.
  const reportsDelta: KpiDelta | null = data
    ? computeYoyDelta(data.reports_by_year)
    : null
  const reportsSparkline: readonly number[] | null = data
    ? extractSparklineSeries(data.reports_by_year)
    : null

  function onRetry(): void {
    void query.refetch()
  }

  return (
    <section
      data-testid="kpi-strip"
      aria-labelledby="kpi-strip-heading"
      className="grid grid-cols-3 gap-4 lg:grid-cols-6"
    >
      <h2 id="kpi-strip-heading" className="sr-only">
        Key performance indicators
      </h2>

      <ScalarCard
        testid="kpi-card-total-reports"
        label="Total Reports"
        value={data?.total_reports}
        state={commonState}
        onRetry={stripState === 'error' ? onRetry : undefined}
        delta={reportsDelta}
        sparkline={reportsSparkline}
      />
      <ScalarCard
        testid="kpi-card-total-incidents"
        label="Total Incidents"
        value={data?.total_incidents}
        state={commonState}
      />
      <ScalarCard
        testid="kpi-card-total-actors"
        label="Total Actors"
        value={data?.total_actors}
        state={commonState}
      />

      <AggregateCard
        testid="kpi-card-top-year"
        label="Top Year"
        entry={
          topYear
            ? { primary: String(topYear.year), secondary: `${topYear.count} reports` }
            : null
        }
        stripState={stripState}
      />
      <AggregateCard
        testid="kpi-card-top-motivation"
        label="Top Motivation"
        entry={
          topMotivation
            ? { primary: topMotivation.motivation, secondary: `${topMotivation.count} incidents` }
            : null
        }
        stripState={stripState}
      />
      <AggregateCard
        testid="kpi-card-top-group"
        label="Top Group"
        entry={
          topGroup
            ? { primary: topGroup.name, secondary: `${topGroup.report_count} reports` }
            : null
        }
        stripState={stripState}
      />
    </section>
  )
}

interface ScalarCardProps {
  testid: string
  label: string
  value: number | undefined
  state: KPICardState
  onRetry?: () => void
  delta?: KpiDelta | null
  sparkline?: readonly number[] | null
}

function ScalarCard({
  testid,
  label,
  value,
  state,
  onRetry,
  delta,
  sparkline,
}: ScalarCardProps): JSX.Element {
  return (
    <div data-testid={testid} className="flex">
      <KPICard
        label={label}
        value={state === 'populated' ? value : undefined}
        state={state}
        onRetry={onRetry}
        delta={delta}
        sparkline={sparkline}
      />
    </div>
  )
}

interface AggregateCardProps {
  testid: string
  label: string
  entry: { primary: string; secondary: string } | null
  stripState: 'loading' | 'error' | 'ready'
}

function AggregateCard({
  testid,
  label,
  entry,
  stripState,
}: AggregateCardProps): JSX.Element {
  let state: KPICardState
  let value: string | undefined
  let subtext: string | undefined

  if (stripState === 'loading') {
    state = 'loading'
  } else if (stripState === 'error') {
    state = 'error'
  } else if (entry == null) {
    state = 'empty'
  } else {
    state = 'populated'
    value = entry.primary
    subtext = entry.secondary
  }

  return (
    <div data-testid={testid} className="flex">
      <KPICard label={label} value={value} subtext={subtext} state={state} />
    </div>
  )
}
