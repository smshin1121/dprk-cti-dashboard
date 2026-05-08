/**
 * Phase 3 Slice 3 D-1 — CorrelationWarningChips T9 implementation.
 *
 * Renders one chip per `interpretation.warnings[]` entry. Each chip
 * carries `data-testid="warning-chip-<code>"` plus
 * `data-severity="info|warn"` so the locale-keyed copy (T11) can
 * change without test churn. Empty `warnings: []` returns null —
 * no container, no testid leak per Plan §B8 (e).
 */

import type { CorrelationWarning } from '../../../lib/api/schemas'

export interface CorrelationWarningChipsProps {
  warnings: CorrelationWarning[]
}

export function CorrelationWarningChips({
  warnings,
}: CorrelationWarningChipsProps): JSX.Element | null {
  if (warnings.length === 0) return null

  return (
    <ul className="flex flex-wrap gap-2" aria-label="Correlation warnings">
      {warnings.map((w) => (
        <li
          key={w.code}
          data-testid={`warning-chip-${w.code}`}
          data-severity={w.severity}
          className={
            w.severity === 'warn'
              ? 'rounded-none border border-border-strong bg-surface px-2 py-1 text-xs text-ink'
              : 'rounded-none border border-border-card bg-app px-2 py-1 text-xs text-ink-muted'
          }
        >
          {w.message}
        </li>
      ))}
    </ul>
  )
}
