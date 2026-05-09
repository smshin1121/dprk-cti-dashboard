/**
 * Phase 3 Slice 3 D-1 — CorrelationWarningChips T11 implementation.
 *
 * Renders one chip per `interpretation.warnings[]` entry. Each chip
 * carries `data-testid="warning-chip-<code>"` plus
 * `data-severity="info|warn"` so the locale-keyed copy can change
 * without test churn. Empty `warnings: []` returns null — no
 * container, no testid leak per Plan §B8 (e).
 *
 * Copy resolution: per CONTRACT.md §2 the chip text comes from
 * `correlation.warnings.<code>` in the active i18n bundle. The BE
 * still ships `w.message` for parity with the response shape; we
 * pass it as `defaultValue` so an unrecognised code (BE adds a 7th
 * code before FE catches up) renders the BE copy rather than a raw
 * key string.
 */

import { useTranslation } from 'react-i18next'

import type { CorrelationWarning } from '../../../lib/api/schemas'

export interface CorrelationWarningChipsProps {
  warnings: CorrelationWarning[]
}

export function CorrelationWarningChips({
  warnings,
}: CorrelationWarningChipsProps): JSX.Element | null {
  const { t } = useTranslation()

  if (warnings.length === 0) return null

  return (
    <ul className="flex flex-wrap gap-2" aria-label={t('correlation.warnings.ariaLabel')}>
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
          {t(`correlation.warnings.${w.code}`, { defaultValue: w.message })}
        </li>
      ))}
    </ul>
  )
}
