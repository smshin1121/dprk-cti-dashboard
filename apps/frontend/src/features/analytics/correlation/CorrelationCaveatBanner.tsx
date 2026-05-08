/**
 * Phase 3 Slice 3 D-1 — CorrelationCaveatBanner T7 RED stub.
 *
 * Sticky "correlation ≠ causation" banner with dismiss-once-per-tab
 * persistence (Q3 default = sessionStorage). T9 implements via
 * `useSyncExternalStore` over a tiny zustand+sessionStorage slice
 * keyed `correlation.banner.dismissed`. Memory anchors:
 *   - `pitfall_zustand_useSyncExternalStore_layout_effect`
 *     (skip first emit via `isInitialMountRef`)
 *   - Q3 §8 — sessionStorage NOT localStorage, so no `<session_uuid>`
 *     suffix is needed. Plan §0.1 amendment 2026-05-08 (T7 dispatch)
 *     aligns §5 risk row to Q3 default.
 */

export function CorrelationCaveatBanner(): JSX.Element {
  throw new Error(
    'NotImplementedError: CorrelationCaveatBanner T7 RED stub — T9 not yet implemented.',
  )
}
