/**
 * Motivation donut — design doc §4.2 area [D] secondary viz.
 * Plan D1 + D8 + D9 (PR #13 Group H).
 *
 * Data: `useDashboardSummary()` — SAME hook KPIStrip uses. React
 * Query's cache shares the `['dashboard', 'summary', filters]` entry
 * across every subscriber under the same filter set, so mounting
 * KPIStrip + MotivationDonut + YearBar together fires ONE network
 * request, not three. Tests pin this invariant.
 *
 * Rationale for reusing the dashboard summary:
 *   - The BE already returns `incidents_by_motivation` inside
 *     `/dashboard/summary` (plan D6 aggregator). Adding a separate
 *     `/analytics/motivations` endpoint would duplicate that path
 *     for no gain — the filter contract is identical.
 *   - Plan D9 locks the per-viz query separation at the analytics
 *     endpoints (attack_matrix / trend / geo) — the motivation
 *     donut and year bar stay on the dashboard summary scope
 *     because their data is literally a slice of that response.
 *
 * Empty UX:
 *   When `incidents_by_motivation` is empty, render an empty card
 *   (not a 0-slice donut — Recharts would draw a degenerate shape).
 */

import {
  Cell,
  Pie,
  PieChart,
  Tooltip,
  type TooltipProps,
} from 'recharts'
import { useTranslation } from 'react-i18next'

import { cn } from '../../lib/utils'
import { useDashboardSummary } from './useDashboardSummary'

// Six colors — more than a realistic top-motivations set, so we
// rotate safely. HSL rotation keeps them distinguishable.
const COLORS = [
  'hsl(210 70% 50%)',
  'hsl(340 70% 55%)',
  'hsl(150 65% 45%)',
  'hsl(40 80% 50%)',
  'hsl(280 60% 55%)',
  'hsl(20 80% 55%)',
]

const CHART_SIZE = 240
const INNER_RADIUS = 60
const OUTER_RADIUS = 100

interface DonutTooltipProps extends TooltipProps<number, string> {}

function DonutTooltip({ active, payload }: DonutTooltipProps): JSX.Element | null {
  if (!active || !payload || payload.length === 0) return null
  const item = payload[0]
  return (
    <div
      data-testid="motivation-donut-tooltip"
      className="rounded border border-border-card bg-surface px-2 py-1 text-xs text-ink shadow"
    >
      <span className="font-semibold">{String(item.name ?? '')}</span>:{' '}
      <span>{String(item.value ?? 0)}</span>
    </div>
  )
}

export function MotivationDonut(): JSX.Element {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch } = useDashboardSummary()

  if (isLoading) {
    return (
      <div
        data-testid="motivation-donut-loading"
        role="status"
        aria-busy="true"
        className="h-64 animate-pulse rounded border border-border-card bg-surface"
      />
    )
  }

  if (isError) {
    return (
      <div
        data-testid="motivation-donut-error"
        role="alert"
        className="flex h-64 flex-col items-center justify-center gap-3 rounded border border-border-card bg-surface p-6"
      >
        <p className="text-sm text-ink-muted">{t('dashboard.error')}</p>
        <button
          type="button"
          data-testid="motivation-donut-retry"
          onClick={() => void refetch()}
          className={cn(
            'rounded border border-border-card bg-app px-3 py-1.5 text-xs text-ink',
            'hover:border-signal focus:outline-none focus:ring-2 focus:ring-ring',
          )}
        >
          {t('list.retry')}
        </button>
      </div>
    )
  }

  const items = data?.incidents_by_motivation ?? []
  const isEmpty = items.length === 0

  if (isEmpty) {
    return (
      <section
        data-testid="motivation-donut-empty"
        className="flex h-64 flex-col items-center justify-center gap-2 rounded border border-border-card bg-surface p-6"
      >
        <h3 className="text-sm font-semibold text-ink">
          {t('dashboard.motivationDonut.title')}
        </h3>
        <p className="text-sm text-ink-muted">
          {t('dashboard.motivationDonut.empty')}
        </p>
      </section>
    )
  }

  return (
    <section
      data-testid="motivation-donut"
      aria-labelledby="motivation-donut-heading"
      className="rounded border border-border-card bg-surface p-4"
    >
      <h3
        id="motivation-donut-heading"
        className="mb-3 text-sm font-semibold text-ink"
      >
        {t('dashboard.motivationDonut.title')}
      </h3>
      <PieChart width={CHART_SIZE} height={CHART_SIZE}>
        <Pie
          data={items as unknown as Array<Record<string, unknown>>}
          dataKey="count"
          nameKey="motivation"
          innerRadius={INNER_RADIUS}
          outerRadius={OUTER_RADIUS}
          isAnimationActive={false}
        >
          {items.map((item, index) => (
            <Cell
              key={item.motivation}
              data-testid={`motivation-donut-slice-${item.motivation}`}
              data-motivation={item.motivation}
              data-count={item.count}
              fill={COLORS[index % COLORS.length]}
            />
          ))}
        </Pie>
        <Tooltip content={<DonutTooltip />} />
      </PieChart>
    </section>
  )
}
