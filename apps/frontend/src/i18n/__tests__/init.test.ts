import { describe, expect, it } from 'vitest'

import { i18n, DEFAULT_LOCALE, SUPPORTED_LOCALES } from '../index'

describe('i18n bootstrap', () => {
  it('initializes synchronously with inline resources', () => {
    expect(i18n.isInitialized).toBe(true)
    // `hasResourceBundle` fails if resources were lazy-loaded / not
    // present after init. We explicitly locked inline resources so
    // the first render never faces a missing-bundle paint.
    expect(i18n.hasResourceBundle('ko', 'translation')).toBe(true)
    expect(i18n.hasResourceBundle('en', 'translation')).toBe(true)
  })

  it('defaults to Korean when no preference is stored', () => {
    // Plan D5: default locale = ko. fallbackLng = ko too, so even if
    // detection returns an unsupported language, we land on ko.
    expect(DEFAULT_LOCALE).toBe('ko')
  })

  it('exposes exactly the 2 supported locales (ko, en) — D5 scope lock', () => {
    expect(SUPPORTED_LOCALES).toEqual(['ko', 'en'])
  })

  it('translates a shell nav key in both locales', () => {
    expect(i18n.getResource('ko', 'translation', 'shell.nav.dashboard')).toBe(
      '대시보드',
    )
    expect(i18n.getResource('en', 'translation', 'shell.nav.dashboard')).toBe(
      'Dashboard',
    )
  })

  it('translates every command id in both locales (Group D + Group F bridge)', () => {
    const ids = [
      'nav.dashboard',
      'nav.reports',
      'nav.incidents',
      'nav.actors',
      'nav.correlation',
      'filters.clear',
      'auth.logout',
    ] as const
    for (const id of ids) {
      const ko = i18n.getResource('ko', 'translation', `commands.${id}`)
      const en = i18n.getResource('en', 'translation', `commands.${id}`)
      expect(typeof ko).toBe('string')
      expect(ko.length).toBeGreaterThan(0)
      expect(typeof en).toBe('string')
      expect(en.length).toBeGreaterThan(0)
      expect(ko).not.toBe(en)
    }
  })

  it('translates every PR 2 dashboard workspace key in both locales (L11 9-key contract)', () => {
    // Per `docs/plans/dashboard-workspace-retrofit.md` L11 + Codex F5
    // (round-1) — eslint-plugin-i18next is NOT configured in this
    // repo, so this presence assertion is the contract that catches a
    // future refactor accidentally dropping or renaming any of the 9
    // keys the new PR 2 dashboard workspace uses.
    //
    // Cross-locale parity: most keys MUST resolve to visually distinct
    // copy in ko vs en (a copy-paste bug that ships ko = en text would
    // silently regress Korean readers). The single exception is
    // `dashboard.alerts.phase4Pill` — "Phase 4" is a project version
    // identifier (the empty-state lines also keep the literal "Phase 4"
    // prefix untranslated, e.g. "Phase 4 — 실시간 알림 미연동"), so
    // the pill is intentionally identical in both locales.
    const PHASE_INVARIANT_KEYS = new Set([
      'dashboard.alerts.phase4Pill',
    ])
    const keys = [
      'dashboard.heading.threatOverview',
      'dashboard.period.label',
      'dashboard.period.hint',
      'dashboard.alerts.phase4Pill',
      'dashboard.alerts.emptyState',
      'dashboard.recent.emptyState',
      'dashboard.drilldown.emptyState',
      'dashboard.actorNetwork.title',
      'dashboard.actorNetwork.plannedEmptyState',
      // PR 3 T10/T12 fold — cap-breach notice surfaces only when the
      // BE flags `cap_breached: true` and the actor selection forced
      // out non-selected high-degree endpoints (plan §5 row #7 +
      // L7). Both locales translate distinctly so the copy-paste
      // guard catches drift.
      'dashboard.actorNetwork.capBreachedNotice',
    ] as const
    for (const key of keys) {
      const ko = i18n.getResource('ko', 'translation', key)
      const en = i18n.getResource('en', 'translation', key)
      expect(typeof ko, `ko missing ${key}`).toBe('string')
      expect(ko.length, `ko empty ${key}`).toBeGreaterThan(0)
      expect(typeof en, `en missing ${key}`).toBe('string')
      expect(en.length, `en empty ${key}`).toBeGreaterThan(0)
      if (PHASE_INVARIANT_KEYS.has(key)) {
        // The invariant: pill copy is "Phase 4" in BOTH locales.
        expect(ko, `${key} should be "Phase 4" invariant in ko`).toBe('Phase 4')
        expect(en, `${key} should be "Phase 4" invariant in en`).toBe('Phase 4')
      } else {
        expect(
          ko,
          `${key} should differ between ko and en (copy-paste guard)`,
        ).not.toBe(en)
      }
    }
  })

  it('translates every Phase 3 Slice 3 D-1 correlation key in both locales (T11 contract)', () => {
    // Per `docs/plans/correlation-fe.md` §4 T11 (i18n keys for the 5
    // correlation components) + memory `pattern_cross_locale_parity_with_invariant_allowlist`.
    //
    // Cross-locale parity: most correlation keys MUST resolve to
    // visually distinct copy in ko vs en (a copy-paste regression
    // would silently ship English-only Korean for the analyst flow).
    // The allowlisted exceptions are universal scientific names
    // (Pearson / Spearman are romanised identically by Korean
    // technical UIs that surface them as a method label) and the
    // ISO 8601 date placeholder which is a literal format token,
    // not a translatable string.
    const CORRELATION_INVARIANT_KEYS = new Set([
      'correlation.method.pearson',
      'correlation.method.spearman',
      'correlation.filters.datePlaceholder',
    ])
    const INVARIANT_VALUES: Record<string, string> = {
      'correlation.method.pearson': 'Pearson',
      'correlation.method.spearman': 'Spearman',
      'correlation.filters.datePlaceholder': 'YYYY-MM-DD',
    }
    const keys = [
      'correlation.page.heading',
      'correlation.methodToggle.ariaLabel',
      'correlation.method.pearson',
      'correlation.method.spearman',
      'correlation.state.emptyPickXY',
      'correlation.state.loading',
      'correlation.state.errorInsufficientSample',
      'correlation.state.errorIdenticalSeries',
      'correlation.state.errorUnknown',
      'correlation.filters.xSeriesLabel',
      'correlation.filters.ySeriesLabel',
      'correlation.filters.xPickerPlaceholder',
      'correlation.filters.yPickerPlaceholder',
      'correlation.filters.dateFromLabel',
      'correlation.filters.dateToLabel',
      'correlation.filters.datePlaceholder',
      'correlation.caveat.title',
      'correlation.caveat.body',
      'correlation.caveat.dismiss',
      'correlation.chart.caption',
      'correlation.warnings.ariaLabel',
      'correlation.warnings.non_stationary_suspected',
      'correlation.warnings.outlier_influence',
      'correlation.warnings.sparse_window',
      'correlation.warnings.cross_rooted_pair',
      'correlation.warnings.identity_or_containment_suspected',
      'correlation.warnings.low_count_suppressed_cells',
    ] as const
    for (const key of keys) {
      const ko = i18n.getResource('ko', 'translation', key)
      const en = i18n.getResource('en', 'translation', key)
      expect(typeof ko, `ko missing ${key}`).toBe('string')
      expect(ko.length, `ko empty ${key}`).toBeGreaterThan(0)
      expect(typeof en, `en missing ${key}`).toBe('string')
      expect(en.length, `en empty ${key}`).toBeGreaterThan(0)
      if (CORRELATION_INVARIANT_KEYS.has(key)) {
        const expected = INVARIANT_VALUES[key]
        expect(ko, `${key} should be "${expected}" invariant in ko`).toBe(expected)
        expect(en, `${key} should be "${expected}" invariant in en`).toBe(expected)
      } else {
        expect(
          ko,
          `${key} should differ between ko and en (copy-paste guard)`,
        ).not.toBe(en)
      }
    }
  })
})
