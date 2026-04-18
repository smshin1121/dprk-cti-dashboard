/**
 * Plan D5 + D4 isolation invariant: locale must NEVER leak into URL
 * state or React Query cache keys. These are the two side-channels
 * that would cause locale-scoped cache misses or unreviewable URL
 * diffs if a future PR accidentally wired locale into either.
 */

import { describe, expect, it } from 'vitest'

import { queryKeys } from '../../lib/queryKeys'
import {
  encodeUrlState,
  URL_STATE_KEYS,
  EMPTY_URL_STATE,
} from '../../lib/urlState'
import { i18n } from '../index'

describe('locale isolation', () => {
  it('URL_STATE_KEYS whitelist does not include any locale-related key', () => {
    const joined = URL_STATE_KEYS.join(' ').toLowerCase()
    expect(joined).not.toContain('locale')
    expect(joined).not.toContain('lang')
    expect(joined).not.toContain('lng')
    expect(joined).not.toContain('i18n')
  })

  it('encodeUrlState output never contains a locale-named param regardless of language', async () => {
    await i18n.changeLanguage('ko')
    const koParams = encodeUrlState({
      ...EMPTY_URL_STATE,
      dateFrom: '2026-01-01',
      groupIds: [1, 3],
    })

    await i18n.changeLanguage('en')
    const enParams = encodeUrlState({
      ...EMPTY_URL_STATE,
      dateFrom: '2026-01-01',
      groupIds: [1, 3],
    })

    expect(koParams.toString()).toBe(enParams.toString())
    for (const p of [koParams, enParams]) {
      for (const key of p.keys()) {
        expect(key.toLowerCase()).not.toMatch(/^(locale|lang|lng|i18n)$/)
      }
    }
  })

  it('React Query cache keys do not include locale — dashboardSummary', async () => {
    await i18n.changeLanguage('ko')
    const koKey = queryKeys.dashboardSummary({
      date_from: '2026-01-01',
      group_id: [1, 3],
    })

    await i18n.changeLanguage('en')
    const enKey = queryKeys.dashboardSummary({
      date_from: '2026-01-01',
      group_id: [1, 3],
    })

    expect(koKey).toEqual(enKey)
  })

  it('React Query cache keys do not include locale — analytics family', async () => {
    const filters = { date_from: '2026-01-01', group_id: [1] }

    await i18n.changeLanguage('ko')
    const koAttack = queryKeys.analyticsAttackMatrix(filters, { top_n: 30 })
    const koTrend = queryKeys.analyticsTrend(filters)
    const koGeo = queryKeys.analyticsGeo(filters)

    await i18n.changeLanguage('en')
    const enAttack = queryKeys.analyticsAttackMatrix(filters, { top_n: 30 })
    const enTrend = queryKeys.analyticsTrend(filters)
    const enGeo = queryKeys.analyticsGeo(filters)

    expect(koAttack).toEqual(enAttack)
    expect(koTrend).toEqual(enTrend)
    expect(koGeo).toEqual(enGeo)
  })
})
