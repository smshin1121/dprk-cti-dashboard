/**
 * Reports-by-year bar chart — design doc §4.2 area [D] secondary
 * viz. Plan D1 + D8 + D9 (PR #13 Group H).
 *
 * Same data strategy as MotivationDonut: reads from
 * `useDashboardSummary()` so KPIStrip + MotivationDonut + YearBar
 * all share ONE `/dashboard/summary` fetch when mounted together.
 * No new analytics endpoint needed — `reports_by_year` already
 * lives on the summary response.
 *
 * Year ordering:
 *   The BE aggregator returns `reports_by_year` sorted by year desc
 *   (newest first). We reverse for chart rendering so the X-axis
 *   reads left-to-right oldest-to-newest — standard time-series UX.
 *
 * Empty UX:
 *   When `reports_by_year` is empty, render an empty card instead
 *   of a 0-bar chart.
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from 'recharts'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import { cn } from '../../lib/utils'
import { useDashboardSummary } from './useDashboardSummary'

const CHART_WIDTH = 480
const CHART_HEIGHT = 240

interface YearTooltipProps extends TooltipProps<number, string> {}

function YearTooltip({ active, payload, label }: YearTooltipProps): JSX.Element | null {
  if (!active || !payload || payload.length === 0) return null
  return (
    <div
      data-testid="year-bar-tooltip"
      className="rounded border border-border-card bg-surface px-2 py-1 text-xs text-ink shadow"
    >
      <span className="font-semibold">{String(label ?? '')}</span>:{' '}
      <span>{String(payload[0].value ?? 0)}</span>
    </div>
  )
}

export function YearBar(): JSX.Element {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch } = useDashboardSummary()

  // Reverse into ascending order for the X-axis. Guarded inside
  // useMemo so the Bar component's data prop identity stays stable
  // across renders when the summary hasn't changed.
  const chartData = useMemo(() => {
    if (!data) return []
    return [...data.reports_by_year].sort((a, b) => a.year - b.year)
  }, [data])

  if (isLoading) {
    return (
      <div
        data-testid="year-bar-loading"
        role="status"
        aria-busy="true"
        className="h-64 animate-pulse rounded border border-border-card bg-surface"
      />
    )
  }

  if (isError) {
    return (
      <div
        data-testid="year-bar-error"
        role="alert"
        className="flex h-64 flex-col items-center justify-center gap-3 rounded border border-border-card bg-surface p-6"
      >
        <p className="text-sm text-ink-muted">{t('dashboard.error')}</p>
        <button
          type="button"
          data-testid="year-bar-retry"
          onClick={() => void refetch()}
          className={cn(
            'rounded border border-border-card bg-app px-3 py-1.5 text-xs text-ink',
            'hover:border-signal focus:outline-none focus:ring-2 focus:ring-signal',
          )}
        >
          {t('list.retry')}
        </button>
      </div>
    )
  }

  const isEmpty = chartData.length === 0

  if (isEmpty) {
    return (
      <section
        data-testid="year-bar-empty"
        className="flex h-64 flex-col items-center justify-center gap-2 rounded border border-border-card bg-surface p-6"
      >
        <h3 className="text-sm font-semibold text-ink">
          {t('dashboard.yearBar.title')}
        </h3>
        <p className="text-sm text-ink-muted">{t('dashboard.yearBar.empty')}</p>
      </section>
    )
  }

  return (
    <section
      data-testid="year-bar"
      aria-labelledby="year-bar-heading"
      className="rounded border border-border-card bg-surface p-4"
    >
      <h3
        id="year-bar-heading"
        className="mb-3 text-sm font-semibold text-ink"
      >
        {t('dashboard.yearBar.title')}
      </h3>
      <BarChart
        width={CHART_WIDTH}
        height={CHART_HEIGHT}
        data={chartData}
        margin={{ top: 8, right: 16, bottom: 20, left: 0 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(210 10% 85%)" />
        <XAxis
          dataKey="year"
          tick={{ fontSize: 11, fill: 'hsl(210 15% 40%)' }}
          tickLine={false}
        />
        <YAxis
          tick={{ fontSize: 11, fill: 'hsl(210 15% 40%)' }}
          tickLine={false}
          axisLine={false}
        />
        <Tooltip content={<YearTooltip />} cursor={{ fill: 'hsl(210 10% 95%)' }} />
        <Bar
          dataKey="count"
          fill="hsl(210 70% 50%)"
          radius={[4, 4, 0, 0]}
          isAnimationActive={false}
          data-testid="year-bar-series"
        />
      </BarChart>
    </section>
  )
}
