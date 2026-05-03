/**
 * Six-card KPI strip — plan §1 / §4 Group E deliverable. Consumes
 * `useDashboardSummary()` and maps the six slots required by
 * design doc §4.2 area [B]:
 *
 *   1. Total Reports        (scalar)
 *   2. Total Incidents      (scalar)
 *   3. Total Actors         (scalar)
 *   4. Top Year             (reports_by_year → max by count)
 *   5. Top Motivation       (incidents_by_motivation[0])
 *   6. Top Group            (top_groups[0])
 *
 * State propagation (plan D11):
 *   - Query loading    → every card shows its own skeleton (six
 *                        aria-busy tiles; no global overlay).
 *   - Query errored    → every card shows the inline error message;
 *                        a SINGLE retry button lives on the first
 *                        card so a rage-click can't fire six
 *                        concurrent refetches.
 *   - Query succeeded  → scalar cards always populated (even at 0,
 *                        which is semantically "zero results" not
 *                        "no data"); array-derived cards fall back
 *                        to `empty` state when the corresponding
 *                        BE array is empty.
 *
 * The BE `reports_by_year` is not guaranteed to be sorted, so we
 * pick the top year by `max(count)` locally. `incidents_by_motivation`
 * and `top_groups` are returned sorted by count desc (see
 * `dashboard_aggregator`), so we just take the first entry.
 */

import type {
  DashboardMotivationCount,
  DashboardTopGroup,
  DashboardYearCount,
} from '../../lib/api/schemas'
import { KPICard, type KPICardState } from './KPICard'
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

  function onRetry(): void {
    void query.refetch()
  }

  // Only the first card carries the retry button when the strip is
  // errored — see KPIStrip docstring + D11 rationale.
  return (
    <section
      data-testid="kpi-strip"
      aria-labelledby="kpi-strip-heading"
      className="flex flex-wrap gap-8 p-6"
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
}

function ScalarCard({
  testid,
  label,
  value,
  state,
  onRetry,
}: ScalarCardProps): JSX.Element {
  // Wraps a KPICard with a stable inner test hook so the strip can
  // target "the Total Reports card" without relying on ordering.
  return (
    <div data-testid={testid} className="flex">
      <KPICard
        label={label}
        value={state === 'populated' ? value : undefined}
        state={state}
        onRetry={onRetry}
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
  // Aggregate cards never carry a retry button — only the first
  // scalar card in the strip does, per the strip-wide shared retry
  // described in the module docstring.
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
