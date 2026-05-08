/**
 * Phase 3 Slice 3 D-1 — CorrelationWarningChips T7 RED stub.
 *
 * Renders one chip per `interpretation.warnings[]` entry. Each chip's
 * copy is keyed by `correlation.warnings.<code>` in i18n (T11 — six
 * codes: non_stationary_suspected, outlier_influence, sparse_window,
 * cross_rooted_pair, identity_or_containment_suspected,
 * low_count_suppressed_cells). Severity styling: `info` vs `warn`.
 *
 * Empty `warnings: []` renders nothing (no container, no testid leak).
 */

import type { CorrelationWarning } from '../../../lib/api/schemas'

export interface CorrelationWarningChipsProps {
  warnings: CorrelationWarning[]
}

export function CorrelationWarningChips(
  _props: CorrelationWarningChipsProps,
): JSX.Element {
  throw new Error(
    'NotImplementedError: CorrelationWarningChips T7 RED stub — T9 not yet implemented.',
  )
}
