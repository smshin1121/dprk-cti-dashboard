/**
 * Phase 3 Slice 3 D-1 — CorrelationFilters T7 RED stub.
 *
 * X / Y / date-range / method controls. Per
 * `pattern_tdd_stub_for_red_collection` — throws on render so T7
 * tests fail at runtime with a traceable message; T9 implements the
 * real form and connects it to URL state via `useFilterUrlSync` (or
 * a per-page successor).
 */

export interface CorrelationFiltersProps {
  // Left intentionally minimal at T7 — T9 fills in.
  // Stub throws before any prop wiring matters.
}

export function CorrelationFilters(_props: CorrelationFiltersProps): JSX.Element {
  throw new Error(
    'NotImplementedError: CorrelationFilters T7 RED stub — T9 not yet implemented.',
  )
}
