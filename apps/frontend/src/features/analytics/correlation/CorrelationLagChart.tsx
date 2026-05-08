/**
 * Phase 3 Slice 3 D-1 — CorrelationLagChart T9 implementation.
 *
 * Recharts `LineChart` at fixed 480×240 (Plan §B4 + the same
 * happy-dom + recharts convention used by `TrendChart` /
 * `MotivationDonut` / `YearBar` — `ResponsiveContainer` measuring
 * is unreliable under happy-dom). Plots the 49-cell `lag_grid` for
 * both methods (Pearson + Spearman) with a single active highlight
 * driven by the `method` prop.
 *
 * Per-method active markers (`line-pearson` / `line-spearman`) are
 * rendered at the page level (`CorrelationPage`), not here — the
 * URL-hydrate test asserts them synchronously before the populated
 * branch mounts, so they need to live independent of the chart's
 * conditional render. Recharts' `<Line>` also forwards
 * `data-testid` to multiple sub-elements per
 * `pitfall_recharts_testid_multielement`, which would have produced
 * ambiguous matches anyway.
 *
 * Series colors come from `dashboard/_palette` (Tol-derived
 * `chartSeriesColor` + `CHART_CHROME` chrome literals) — same
 * palette every other dashboard chart uses. Using `hsl(var(...))`
 * with non-existent CSS variables would render invisible strokes
 * in the browser (no token fallback exists for those names).
 */

import { useMemo } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { CHART_CHROME, chartSeriesColor } from '../../dashboard/_palette'
import type { CorrelationResponse } from '../../../lib/api/schemas'

const CHART_WIDTH = 480
const CHART_HEIGHT = 240

export interface CorrelationLagChartProps {
  data: CorrelationResponse
  method: 'pearson' | 'spearman'
}

interface LagPoint {
  lag: number
  pearson_r: number | null
  spearman_r: number | null
}

export function CorrelationLagChart({ data, method }: CorrelationLagChartProps): JSX.Element {
  const chartData = useMemo<LagPoint[]>(
    () =>
      data.lag_grid.map((cell) => ({
        lag: cell.lag,
        pearson_r: cell.pearson.r,
        spearman_r: cell.spearman.r,
      })),
    [data],
  )

  return (
    <div className="flex flex-col gap-2">
      <LineChart
        width={CHART_WIDTH}
        height={CHART_HEIGHT}
        data={chartData}
        margin={{ top: 8, right: 16, bottom: 24, left: 32 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke={CHART_CHROME.gridStroke} />
        <XAxis dataKey="lag" tick={{ fontSize: 11, fill: CHART_CHROME.axisTickFill }} />
        <YAxis
          domain={[-1, 1]}
          tick={{ fontSize: 11, fill: CHART_CHROME.axisTickFill }}
        />
        <Tooltip
          contentStyle={{
            background: CHART_CHROME.tooltipBg,
            border: `1px solid ${CHART_CHROME.tooltipBorder}`,
            color: CHART_CHROME.tooltipText,
          }}
        />
        <Line
          type="monotone"
          dataKey="pearson_r"
          stroke={chartSeriesColor(0)}
          strokeWidth={method === 'pearson' ? 2 : 1}
          strokeOpacity={method === 'pearson' ? 1 : 0.3}
          dot={false}
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="spearman_r"
          stroke={chartSeriesColor(1)}
          strokeWidth={method === 'spearman' ? 2 : 1}
          strokeOpacity={method === 'spearman' ? 1 : 0.3}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
      <p className="text-xs text-ink-muted">
        α = {data.alpha} · effective n = {data.effective_n} · period{' '}
        {data.date_from} – {data.date_to}
      </p>
    </div>
  )
}
