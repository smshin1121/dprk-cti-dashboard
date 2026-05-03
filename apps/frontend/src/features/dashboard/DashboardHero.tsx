/**
 * Dashboard hero — Ferrari L4 (plan §6 H1, commit 8).
 *
 * Editorial CTI hero band per DESIGN.md §Spec & Race Surfaces +
 * §Hero Bands hero-band-cinema. Layout:
 *
 *   [caption-uppercase label]
 *   [80px number-display in Rosso Corsa]
 *   [display-md sub-headline]
 *   [primary CTA] [outline CTA]
 *
 * Plan locked Option H1 over H2 per plan §10 Q1: single number-display
 * KPI at the top, NOT a full-bleed photographic hero (the cinematic
 * Ferrari hero presumes a brand image; CTI dashboards have none).
 *
 * Data
 * ----
 * Reads `total_incidents` from `useDashboardSummary()` — the SAME
 * cache slot KPIStrip + MotivationDonut + YearBar + 3 sibling widgets
 * subscribe to. Mounting the hero adds zero network traffic.
 *
 * Plan-vs-impl note (§0.1 deviation, also recorded in commit body)
 * ---------------------------------------------------------------
 * Plan §6.1 specifies "Total active incidents count (RED Rosso Corsa
 * if > threshold)". The BE currently exposes `total_incidents` but
 * not `total_active_incidents` — the active/resolved split is a
 * follow-up schema concern (BE PR C scope). Until that field lands,
 * the hero renders `total_incidents` and the Rosso Corsa color is
 * applied unconditionally (any incident count > 0 reads as
 * dashboard-priority threshold met). When the BE adds an `active`
 * counter, swap the data binding here without changing the visual.
 *
 * State semantics
 * ---------------
 * - Loading: caption + skeleton number block, sub-headline + CTAs
 *   render in their final position so the layout doesn't reflow.
 * - Error: caption "—" placeholder for the number, sub-headline
 *   stays, CTAs stay (CTAs are routes, not data).
 * - Populated: number from total_incidents.
 *
 * No empty branch: the dashboard implies at least 1 incident in the
 * data set; "0 incidents" still renders the number 0 in Rosso Corsa,
 * which is the honest signal.
 */

import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { cn } from '../../lib/utils'
import { useDashboardSummary } from './useDashboardSummary'

const numberFormat = new Intl.NumberFormat('en-US')

export function DashboardHero(): JSX.Element {
  const { t } = useTranslation()
  const { data, isLoading, isError } = useDashboardSummary()

  const formatted =
    isLoading || isError || data == null
      ? '—'
      : numberFormat.format(data.total_incidents)
  const aria = isLoading
    ? t('dashboard.hero.loading')
    : t('dashboard.hero.populatedAria', { count: formatted })

  return (
    <section
      data-testid="dashboard-hero"
      aria-labelledby="dashboard-hero-heading"
      className="flex flex-col gap-4 p-6"
    >
      <span
        data-testid="dashboard-hero-label"
        id="dashboard-hero-heading"
        className="text-[10px] font-cta uppercase tracking-caption text-ink-subtle"
      >
        {t('dashboard.hero.label')}
      </span>

      <span
        data-testid="dashboard-hero-value"
        aria-label={aria}
        aria-live="polite"
        aria-busy={isLoading ? 'true' : 'false'}
        className={cn(
          'block text-[80px] font-cta leading-none tracking-number-display',
          // Rosso Corsa per plan §6.1 — incident count is a CTI
          // priority highlight per the race-position-cell mapping
          // in DESIGN.md §Spec & Race Surfaces. Empty placeholder
          // dash uses ink-muted so a missing number reads as
          // "loading" not "alarm".
          formatted === '—' ? 'text-ink-muted' : 'text-signal',
        )}
      >
        {formatted}
      </span>

      <p
        data-testid="dashboard-hero-subheading"
        className="text-2xl font-display tracking-display text-ink"
      >
        {t('dashboard.hero.subheading')}
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-3">
        <Link
          to="/incidents"
          data-testid="dashboard-hero-cta-primary"
          className={cn(
            'inline-flex h-12 items-center justify-center rounded-none bg-primary px-8 text-sm font-cta uppercase tracking-cta text-primary-foreground',
            'hover:bg-primary-active active:bg-primary-active focus:outline-none focus:ring-2 focus:ring-ring',
          )}
        >
          {t('dashboard.hero.ctaPrimary')}
        </Link>
        <Link
          to="/reports"
          data-testid="dashboard-hero-cta-outline"
          className={cn(
            'inline-flex h-12 items-center justify-center rounded-none border border-ink bg-transparent px-8 text-sm font-cta uppercase tracking-cta text-ink',
            'hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-ring',
          )}
        >
          {t('dashboard.hero.ctaOutline')}
        </Link>
      </div>
    </section>
  )
}
