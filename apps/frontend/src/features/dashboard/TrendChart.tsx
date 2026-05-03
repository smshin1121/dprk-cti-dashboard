/**
 * Monthly-trend line chart — design doc §4.2 area [E] primary viz.
 * Plan D1 + D2 + D9 (PR #13 Group I).
 *
 * Data: `useTrend()` (Group C analytics hook). BE returns the
 * monthly-bucket shape locked in plan D2:
 *
 *     { buckets: [{ month: "YYYY-MM", count: int }] }
 *
 * The BE omits zero-count months (plan D2), so the viz owns any
 * gap-fill semantics. For now we render the buckets verbatim — a
 * missing month between 2026-01 and 2026-03 is a visible gap in the
 * line, which is the honest signal. Gap-fill is a future concern if
 * analyst feedback asks for it.
 *
 * Four render states (review invariant per user):
 *   - loading    → skeleton with `data-testid="trend-chart-loading"`
 *   - error      → inline error card + retry button
 *   - empty      → dedicated empty card (buckets.length === 0)
 *   - populated  → LineChart at fixed dimensions
 *
 * Fixed-size chart (not ResponsiveContainer) matches YearBar /
 * MotivationDonut conventions — ResizeObserver under happy-dom is
 * the known trap; recharts without the responsive wrapper renders
 * deterministically in tests.
 */

import { useMemo } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from 'recharts'
import { useTranslation } from 'react-i18next'

import { useTrend } from '../analytics/useTrend'
import { cn } from '../../lib/utils'
import { CHART_CHROME, chartSeriesColor } from './_palette'

const CHART_WIDTH = 480
const CHART_HEIGHT = 240

interface TrendTooltipProps extends TooltipProps<number, string> {}

function TrendTooltip({ active, payload, label }: TrendTooltipProps): JSX.Element | null {
  if (!active || !payload || payload.length === 0) return null
  return (
    <div
      data-testid="trend-chart-tooltip"
      className="rounded-none border border-border-card bg-surface px-2 py-1 text-xs text-ink shadow"
    >
      <span className="font-semibold">{String(label ?? '')}</span>:{' '}
      <span>{String(payload[0].value ?? 0)}</span>
    </div>
  )
}

export function TrendChart(): JSX.Element {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch } = useTrend()

  // Buckets are already in chronological order from the BE aggregator
  // (see `services/api/src/api/read/analytics_aggregator.py`). Memo
  // keeps the Line data prop identity stable across re-renders.
  const chartData = useMemo(() => {
    if (!data) return []
    return data.buckets
  }, [data])

  if (isLoading) {
    return (
      <div
        data-testid="trend-chart-loading"
        role="status"
        aria-busy="true"
        className="h-64 animate-pulse rounded-none border border-border-card bg-surface"
      />
    )
  }

  if (isError) {
    return (
      <div
        data-testid="trend-chart-error"
        role="alert"
        className="flex h-64 flex-col items-center justify-center gap-3 rounded-none border border-border-card bg-surface p-6"
      >
        <p className="text-sm text-ink-muted">{t('dashboard.error')}</p>
        <button
          type="button"
          data-testid="trend-chart-retry"
          onClick={() => void refetch()}
          className={cn(
            'rounded-none border border-border-card bg-app px-3 py-1.5 text-xs font-cta uppercase tracking-cta text-ink',
            'hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-ring',
          )}
        >
          {t('list.retry')}
        </button>
      </div>
    )
  }

  if (chartData.length === 0) {
    return (
      <section
        data-testid="trend-chart-empty"
        className="flex h-64 flex-col items-center justify-center gap-2 rounded-none border border-border-card bg-surface p-6"
      >
        <h3 className="text-sm font-semibold text-ink">
          {t('dashboard.trendChart.title')}
        </h3>
        <p className="text-sm text-ink-muted">{t('dashboard.trendChart.empty')}</p>
      </section>
    )
  }

  return (
    <section
      data-testid="trend-chart"
      aria-labelledby="trend-chart-heading"
      className="rounded-none border border-border-card bg-surface p-4"
    >
      <h3
        id="trend-chart-heading"
        className="mb-3 text-sm font-semibold text-ink"
      >
        {t('dashboard.trendChart.title')}
      </h3>
      <LineChart
        width={CHART_WIDTH}
        height={CHART_HEIGHT}
        data={chartData}
        margin={{ top: 8, right: 16, bottom: 20, left: 0 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke={CHART_CHROME.gridStroke} />
        <XAxis
          dataKey="month"
          tick={{ fontSize: 11, fill: CHART_CHROME.axisTickFill }}
          tickLine={false}
        />
        <YAxis
          tick={{ fontSize: 11, fill: CHART_CHROME.axisTickFill }}
          tickLine={false}
          axisLine={false}
          allowDecimals={false}
        />
        <Tooltip content={<TrendTooltip />} cursor={{ stroke: CHART_CHROME.gridStroke }} />
        <Line
          type="monotone"
          dataKey="count"
          stroke={chartSeriesColor(0)}
          strokeWidth={2}
          dot={{ r: 3, fill: chartSeriesColor(0) }}
          isAnimationActive={false}
          data-testid="trend-chart-series"
        />
      </LineChart>
    </section>
  )
}
