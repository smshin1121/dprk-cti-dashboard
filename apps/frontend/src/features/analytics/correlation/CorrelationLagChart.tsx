/**
 * Phase 3 Slice 3 D-1 — CorrelationLagChart T7 RED stub.
 *
 * Recharts `LineChart` at fixed 480×240 (B4 + memory
 * `pitfall_jsdom_abortsignal_react_router` predecessor). Plots the
 * 49-cell `lag_grid` for the user-selected method (Pearson default).
 * Memory `pitfall_recharts_testid_multielement` — per-line testids
 * (`line-pearson` / `line-spearman`) for tests; series-shape testids
 * use `getAllByTestId(...).length).toBeGreaterThan(0)`.
 */

import type { CorrelationResponse } from '../../../lib/api/schemas'

export interface CorrelationLagChartProps {
  data: CorrelationResponse
  method: 'pearson' | 'spearman'
}

export function CorrelationLagChart(_props: CorrelationLagChartProps): JSX.Element {
  throw new Error(
    'NotImplementedError: CorrelationLagChart T7 RED stub — T9 not yet implemented.',
  )
}
