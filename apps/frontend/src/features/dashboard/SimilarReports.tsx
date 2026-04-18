/**
 * Similar-reports panel — design doc §4.2 area [E].
 *
 * **Scope: STATIC STUB.** Plan §1 explicit non-goal: report detail
 * views ship in Phase 3. No `/reports/:id/similar` endpoint exists
 * yet, there is no BE similarity algorithm, and without a selected
 * report the concept of "similar" has no anchor.
 *
 * What the stub IS:
 *   - A placeholder slot in the dashboard layout so area [E] has
 *     the right visual weight when Group I ships.
 *   - A readable UI cue (placeholder copy + phase note) so an
 *     analyst who lands on /dashboard before Phase 3 is not
 *     confused about why the panel appears inert.
 *   - Deliberately surfaced in HTML attributes (data-phase-status,
 *     data-phase) so tests, grep, and future refactors can locate
 *     and upgrade the component when Phase 3 endpoints land.
 *
 * What the stub IS NOT:
 *   - Not a fetch — zero React Query hooks, zero network calls.
 *   - Not state-driven — no props, no zustand reads. Identical
 *     markup on every render.
 *
 * When Phase 3 detail endpoints land:
 *   Replace this file's body with a hook-driven render. The
 *   `<section>` scaffold can stay; the placeholder copy + phaseNote
 *   come out; data-phase-status flips from "stub" to "live".
 */

import { useTranslation } from 'react-i18next'

export function SimilarReports(): JSX.Element {
  const { t } = useTranslation()
  return (
    <section
      data-testid="similar-reports-stub"
      data-phase-status="stub"
      data-phase="phase-3"
      aria-labelledby="similar-reports-heading"
      className="flex h-64 flex-col justify-between rounded border border-dashed border-border-card bg-surface p-4"
    >
      <header>
        <h3
          id="similar-reports-heading"
          className="text-sm font-semibold text-ink"
        >
          {t('dashboard.similarReports.title')}
        </h3>
      </header>
      <p
        data-testid="similar-reports-placeholder"
        className="flex-1 pt-4 text-sm text-ink-muted"
      >
        {t('dashboard.similarReports.placeholder')}
      </p>
      <p
        data-testid="similar-reports-phase-note"
        className="text-[11px] uppercase tracking-wider text-ink-subtle"
      >
        {t('dashboard.similarReports.phaseNote')}
      </p>
    </section>
  )
}
