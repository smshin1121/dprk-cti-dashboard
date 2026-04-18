/**
 * Locale toggle — plan D5 (PR #13 Group F).
 *
 * Renders a compact ko ↔ en toggle button. Clicking calls
 * `i18n.changeLanguage(next)` which is intercepted by the detector's
 * `caches: ['localStorage']` and persisted under `i18nextLng`. On the
 * next mount, the detector reads localStorage first (order:
 * localStorage → navigator), so the user's explicit choice wins over
 * the browser's Accept-Language.
 *
 * UI pattern mirrors `ThemeToggle` — a single button cycling through
 * supported locales. With only two locales (ko/en), "cycle" is
 * effectively "swap", but the implementation is future-safe if a
 * third locale lands.
 *
 * Isolation contract (plan D5 + Group F review criterion):
 *   - No React Query cache invalidation on language change.
 *   - No URL-state write on language change (urlState whitelist
 *     excludes locale).
 *   - Persistence via localStorage only (i18next detector's own
 *     cache). The store does not need a separate mirror.
 */

import { useTranslation } from 'react-i18next'

import { cn } from '../lib/utils'
import { SUPPORTED_LOCALES, type SupportedLocale } from '../i18n'

function nextLocale(current: SupportedLocale): SupportedLocale {
  const i = SUPPORTED_LOCALES.indexOf(current)
  return SUPPORTED_LOCALES[(i + 1) % SUPPORTED_LOCALES.length]
}

function isSupported(lng: string): lng is SupportedLocale {
  return (SUPPORTED_LOCALES as readonly string[]).includes(lng)
}

export function LocaleToggle(): JSX.Element {
  const { t, i18n } = useTranslation()

  const currentRaw = i18n.resolvedLanguage ?? i18n.language ?? SUPPORTED_LOCALES[0]
  const current: SupportedLocale = isSupported(currentRaw)
    ? currentRaw
    : SUPPORTED_LOCALES[0]

  function handleClick(): void {
    const target = nextLocale(current)
    void i18n.changeLanguage(target)
  }

  return (
    <button
      type="button"
      data-testid="locale-toggle"
      data-locale={current}
      onClick={handleClick}
      aria-label={t('locale.ariaLabel')}
      className={cn(
        'inline-flex h-6 items-center rounded border border-border-card bg-app px-2 text-[10px] font-semibold uppercase tracking-wider text-ink-muted',
        'hover:border-signal hover:text-ink focus:outline-none focus:ring-2 focus:ring-signal',
      )}
    >
      {current}
    </button>
  )
}
