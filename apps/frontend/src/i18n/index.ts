/**
 * i18next bootstrap — plan D5 lock (PR #13 Group F).
 *
 * Scope (D5 carried verbatim):
 *   - Library: react-i18next + i18next-browser-languagedetector.
 *   - Default locale: ko. Manual toggle in UserMenu overrides detection.
 *   - Translated surface: shell labels + chart titles + empty / error
 *     copy + ⌘K command labels + user-menu labels.
 *   - Excluded: BE domain values (actor names, MITRE technique /
 *     tactic names, group aliases), analyst-entered free text.
 *
 * Synchronous init:
 * Resources are imported inline (not fetched asynchronously) so the
 * first React render already has translations available — no FOUC
 * on i18n. i18next init resolves synchronously when no backend is
 * registered, which is the case here (no `.use(Backend)` on the
 * chain).
 *
 * Detector order (localStorage → navigator):
 * The user's explicit choice (persisted in localStorage under the
 * standard `i18nextLng` key by the detector) wins. If no persisted
 * choice, fall back to `navigator.language`. If that fails too,
 * i18next falls back to `fallbackLng = ko`. The "manual toggle"
 * contract in D5 is implemented by LocaleToggle calling
 * `i18n.changeLanguage(...)` which the detector's `caches: ['localStorage']`
 * writes back — no extra persistence layer needed.
 *
 * Isolation contract (URL / React Query):
 *   - i18next's current language is NOT wired into URL state
 *     (`urlState.ts` whitelist is {date_from, date_to, group_id,
 *     view, tab}, no locale).
 *   - No React Query cache key includes language. The tests in
 *     `src/i18n/__tests__/isolation.test.ts` pin both.
 *
 * Typed resources:
 * `Resources` type below matches `ko.json` shape exactly. `i18next`
 * auto-infers translation keys from this module's resources when
 * `@i18next/typescript` plugin is wired — we don't need that yet;
 * components use string literal keys and rely on the runtime miss-
 * key handler (logs warning in dev).
 */

import i18n, { type InitOptions } from 'i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import { initReactI18next } from 'react-i18next'

import en from './en.json'
import ko from './ko.json'

export const SUPPORTED_LOCALES = ['ko', 'en'] as const
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number]

export const DEFAULT_LOCALE: SupportedLocale = 'ko'

/**
 * Exposed for tests that need to reset language state between runs
 * without importing i18next directly. The component API should
 * continue to go through `useTranslation()`.
 */
export { i18n }

// Resource shape — matches ko.json / en.json literally.
export interface Resources {
  shell: {
    nav: {
      dashboard: string
      reports: string
      incidents: string
      actors: string
    }
    brand: string
    search: {
      placeholder: string
      dialogLabel: string
      emptyLabel: string
      inputPlaceholder: string
    }
  }
  userMenu: {
    theme: string
    language: string
    signOut: string
    triggerAriaLabel: string
  }
  locale: {
    ko: string
    en: string
    ariaLabel: string
  }
  commands: Record<string, string>
  list: {
    loading: string
    empty: string
    error: string
    retry: string
    rateLimited: string
  }
  dashboard: {
    empty: string
    error: string
  }
}

// Guarded init so HMR / test resets don't re-initialize and wipe
// language state. `i18n.isInitialized` is the canonical signal.
//
// Why the options object is an explicit `InitOptions` constant:
// `i18n.use(...).use(...).init({...})` narrows `init`'s signature
// on i18next v26 such that passing an object literal inline fails
// `tsc -b` overload resolution. Typing the constant explicitly
// restores the correct overload path. `initImmediate` (i18next
// runtime flag) is no longer in `InitOptions` in v26, so we
// rely on the implicit sync-init behaviour that kicks in when no
// `.use(Backend)` is on the chain.
const initOptions: InitOptions = {
  resources: {
    ko: { translation: ko as Resources },
    en: { translation: en as Resources },
  },
  fallbackLng: DEFAULT_LOCALE,
  supportedLngs: SUPPORTED_LOCALES as unknown as string[],
  // Only run detection order: localStorage first (user choice),
  // then navigator (OS / browser default). Do NOT sniff cookie
  // — we have no server-side cookie for locale; adding that
  // here would be tempting but adds a BE round-trip on no
  // value.
  detection: {
    order: ['localStorage', 'navigator'],
    caches: ['localStorage'],
    lookupLocalStorage: 'i18nextLng',
  },
  interpolation: {
    // React already escapes; i18next's built-in escaper would
    // double-escape user input.
    escapeValue: false,
  },
}

if (!i18n.isInitialized) {
  i18n.use(LanguageDetector).use(initReactI18next).init(initOptions)
}

export default i18n
