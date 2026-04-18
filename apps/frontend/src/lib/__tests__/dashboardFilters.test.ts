import { describe, expect, it } from 'vitest'

import {
  toDashboardSummaryFilters,
  toDashboardSummaryQueryParams,
  type DashboardSummaryFilters,
} from '../dashboardFilters'
import type { FilterState, TlpLevel } from '../../stores/filters'

const ALL_TLP: TlpLevel[] = ['WHITE', 'GREEN', 'AMBER']

function makeState(overrides: Partial<FilterState> = {}): FilterState {
  return {
    dateFrom: null,
    dateTo: null,
    groupIds: [],
    tlpLevels: [],
    setDateRange: () => undefined,
    toggleGroupId: () => undefined,
    toggleTlpLevel: () => undefined,
    clear: () => undefined,
    ...overrides,
  }
}

describe('toDashboardSummaryFilters', () => {
  it('returns an empty object when nothing is filtered', () => {
    expect(toDashboardSummaryFilters(makeState())).toEqual({})
  })

  it('omits date keys when value is null (do not send `null` to BE)', () => {
    const filters = toDashboardSummaryFilters(makeState({ dateFrom: null, dateTo: null }))
    expect(filters).not.toHaveProperty('date_from')
    expect(filters).not.toHaveProperty('date_to')
  })

  it('renames dateFrom/dateTo to BE wire names date_from/date_to', () => {
    const filters = toDashboardSummaryFilters(
      makeState({ dateFrom: '2026-01-01', dateTo: '2026-04-18' }),
    )
    expect(filters.date_from).toBe('2026-01-01')
    expect(filters.date_to).toBe('2026-04-18')
  })

  it('omits group_id when groupIds is empty', () => {
    const filters = toDashboardSummaryFilters(makeState({ groupIds: [] }))
    expect(filters).not.toHaveProperty('group_id')
  })

  it('renames groupIds to BE wire name group_id (singular, repeatable)', () => {
    const filters = toDashboardSummaryFilters(makeState({ groupIds: [3, 5] }))
    expect(filters.group_id).toEqual([3, 5])
  })

  // Set-semantic canonicalization at the wire boundary. UI toggle
  // order is preserved in the store (so the FE can reason about it
  // for things like "most recently toggled"), but the BE doesn't
  // care about order — `group_id IN (1,3)` matches `IN (3,1)`. Two
  // different orderings would otherwise produce two distinct cache
  // keys for the same logical filter (cache miss + redundant
  // network round-trip every time the analyst rearranges checkboxes).
  describe('groupIds canonicalization', () => {
    it('sorts group_id ascending so equivalent sets share output', () => {
      const sorted = toDashboardSummaryFilters(makeState({ groupIds: [3, 1, 5] }))
      expect(sorted.group_id).toEqual([1, 3, 5])
    })

    it('identical sets toggled in different orders produce identical filters', () => {
      const a = toDashboardSummaryFilters(makeState({ groupIds: [1, 3] }))
      const b = toDashboardSummaryFilters(makeState({ groupIds: [3, 1] }))
      expect(a).toEqual(b)
    })

    it('does not mutate the caller-owned groupIds array', () => {
      const original = [3, 1, 5]
      toDashboardSummaryFilters(makeState({ groupIds: original }))
      expect(original).toEqual([3, 1, 5])
    })
  })

  // D5 contract: TLP is UI-only. The transform's job is to make
  // it impossible for TLP to leak into a BE call. Three layers of
  // defense — type system (no tlp field on DashboardSummaryFilters),
  // runtime equality (this test), and a third layer in queryKeys.
  describe('TLP isolation contract (D5 lock)', () => {
    it('produces identical output regardless of tlpLevels selection', () => {
      const base = makeState({
        dateFrom: '2026-01-01',
        dateTo: '2026-04-18',
        groupIds: [3, 5],
      })
      const noTlp = toDashboardSummaryFilters({ ...base, tlpLevels: [] })
      const someTlp = toDashboardSummaryFilters({ ...base, tlpLevels: ['AMBER'] })
      const allTlp = toDashboardSummaryFilters({ ...base, tlpLevels: ALL_TLP })
      expect(someTlp).toEqual(noTlp)
      expect(allTlp).toEqual(noTlp)
    })

    it('output JSON contains no tlp markers', () => {
      const filters = toDashboardSummaryFilters(
        makeState({ tlpLevels: ALL_TLP, groupIds: [1] }),
      )
      const json = JSON.stringify(filters).toLowerCase()
      expect(json).not.toContain('tlp')
      expect(json).not.toContain('amber')
      expect(json).not.toContain('green')
      expect(json).not.toContain('white')
    })
  })
})

describe('toDashboardSummaryQueryParams', () => {
  it('returns empty params for empty filters', () => {
    const params = toDashboardSummaryQueryParams({})
    expect(params.toString()).toBe('')
  })

  it('emits date_from / date_to as scalar params', () => {
    const params = toDashboardSummaryQueryParams({
      date_from: '2026-01-01',
      date_to: '2026-04-18',
    })
    expect(params.get('date_from')).toBe('2026-01-01')
    expect(params.get('date_to')).toBe('2026-04-18')
  })

  it('emits one group_id entry per id (BE-repeatable param)', () => {
    const params = toDashboardSummaryQueryParams({ group_id: [3, 5, 7] })
    expect(params.getAll('group_id')).toEqual(['3', '5', '7'])
  })

  it('produces identical query strings for equivalent group sets', () => {
    const a = toDashboardSummaryQueryParams(
      toDashboardSummaryFilters(makeState({ groupIds: [1, 3] })),
    )
    const b = toDashboardSummaryQueryParams(
      toDashboardSummaryFilters(makeState({ groupIds: [3, 1] })),
    )
    expect(a.toString()).toBe(b.toString())
  })

  // Critical D5 contract at the URL boundary — no possible TLP leak
  // even if a future caller tries to spread arbitrary keys into the
  // filters object. The function only knows the documented keys.
  it('never emits any tlp-prefixed param even with extraneous input', () => {
    const params = toDashboardSummaryQueryParams({
      // @ts-expect-error — intentionally smuggle TLP-shaped data
      tlp: 'AMBER',
      // @ts-expect-error
      tlp_levels: ['WHITE', 'GREEN'],
      group_id: [1],
    })
    for (const key of params.keys()) {
      expect(key.toLowerCase()).not.toContain('tlp')
    }
    expect(params.getAll('group_id')).toEqual(['1'])
  })
})

// Static type-level contract — DashboardSummaryFilters has no
// optional/required tlp field. Compiler error here = D5 violation.
const _typeContract: DashboardSummaryFilters = {
  date_from: '2026-01-01',
  date_to: '2026-04-18',
  group_id: [1, 2],
}
void _typeContract
