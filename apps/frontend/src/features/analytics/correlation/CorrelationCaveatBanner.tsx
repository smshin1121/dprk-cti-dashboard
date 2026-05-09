/**
 * Phase 3 Slice 3 D-1 — CorrelationCaveatBanner T11 implementation.
 *
 * Sticky "correlation ≠ causation" banner, dismiss-once-per-tab via
 * sessionStorage (Q3 default — NOT localStorage). The dismissed flag
 * is read synchronously on first render via `useState` initializer
 * so the banner does not flash for users who already dismissed it
 * earlier in the same tab. Copy is sourced from i18n keys
 * `correlation.caveat.{title,body,dismiss}`; tests pin testids only.
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'

const STORAGE_KEY = 'correlation.banner.dismissed'

function readDismissed(): boolean {
  if (typeof window === 'undefined') return false
  return window.sessionStorage.getItem(STORAGE_KEY) === '1'
}

export function CorrelationCaveatBanner(): JSX.Element | null {
  const { t } = useTranslation()
  const [dismissed, setDismissed] = useState<boolean>(readDismissed)

  if (dismissed) return null

  function dismiss(): void {
    window.sessionStorage.setItem(STORAGE_KEY, '1')
    setDismissed(true)
  }

  return (
    <aside
      data-testid="correlation-caveat-banner"
      role="note"
      className="flex items-start justify-between gap-4 rounded-none border border-border-card bg-surface px-md py-sm text-sm text-ink"
    >
      <div className="flex flex-col gap-1">
        <p className="font-semibold">{t('correlation.caveat.title')}</p>
        <p className="text-ink-muted">{t('correlation.caveat.body')}</p>
      </div>
      <button
        type="button"
        data-testid="correlation-caveat-dismiss"
        onClick={dismiss}
        className="rounded-none border border-border-card bg-app px-2 py-1 text-xs font-cta uppercase tracking-cta text-ink hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-ring"
      >
        {t('correlation.caveat.dismiss')}
      </button>
    </aside>
  )
}
