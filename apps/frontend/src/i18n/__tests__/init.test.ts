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
    ] as const
    for (const key of keys) {
      const ko = i18n.getResource('ko', 'translation', key)
      const en = i18n.getResource('en', 'translation', key)
      expect(typeof ko, `ko missing ${key}`).toBe('string')
      expect(ko.length, `ko empty ${key}`).toBeGreaterThan(0)
      expect(typeof en, `en missing ${key}`).toBe('string')
      expect(en.length, `en empty ${key}`).toBeGreaterThan(0)
    }
  })
})
