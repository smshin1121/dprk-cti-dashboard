import { describe, expect, it } from 'vitest'

import {
  toAnalyticsFilters,
  toAttackMatrixQueryParams,
  toGeoQueryParams,
  toIncidentsTrendQueryParams,
  toTrendQueryParams,
  type AnalyticsFilters,
} from '../analyticsFilters'
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

describe('toAnalyticsFilters', () => {
  it('returns empty object when nothing is filtered', () => {
    expect(toAnalyticsFilters(makeState())).toEqual({})
  })

  it('renames store fields to BE wire names', () => {
    const filters = toAnalyticsFilters(
      makeState({
        dateFrom: '2026-01-01',
        dateTo: '2026-04-18',
        groupIds: [3],
      }),
    )
    expect(filters).toEqual({
      date_from: '2026-01-01',
      date_to: '2026-04-18',
      group_id: [3],
    })
  })

  it('omits empty fields from the wire payload', () => {
    const filters = toAnalyticsFilters(
      makeState({ dateFrom: null, dateTo: null, groupIds: [] }),
    )
    expect(filters).not.toHaveProperty('date_from')
    expect(filters).not.toHaveProperty('date_to')
    expect(filters).not.toHaveProperty('group_id')
  })

  // Same canonicalization as dashboardFilters (PR #12 Codex R1 P2
  // regression guard carries forward — set-semantic BE + toggle-order
  // insensitive UI must not diverge in cache keys).
  describe('groupIds canonicalization', () => {
    it('sorts group_id ascending so equivalent sets share output', () => {
      const sorted = toAnalyticsFilters(makeState({ groupIds: [3, 1, 5] }))
      expect(sorted.group_id).toEqual([1, 3, 5])
    })

    it('identical sets toggled in different orders produce identical filters', () => {
      const a = toAnalyticsFilters(makeState({ groupIds: [1, 3] }))
      const b = toAnalyticsFilters(makeState({ groupIds: [3, 1] }))
      expect(a).toEqual(b)
    })

    it('does not mutate the caller-owned groupIds array', () => {
      const original = [3, 1, 5]
      toAnalyticsFilters(makeState({ groupIds: original }))
      expect(original).toEqual([3, 1, 5])
    })
  })

  // D4 lock — TLP must never surface in the wire payload regardless
  // of store state. Three layers of defense mirror dashboardFilters.
  describe('TLP isolation contract (D4 lock)', () => {
    it('produces identical output regardless of tlpLevels selection', () => {
      const base = makeState({
        dateFrom: '2026-01-01',
        dateTo: '2026-04-18',
        groupIds: [3, 5],
      })
      const noTlp = toAnalyticsFilters({ ...base, tlpLevels: [] })
      const someTlp = toAnalyticsFilters({ ...base, tlpLevels: ['AMBER'] })
      const allTlp = toAnalyticsFilters({ ...base, tlpLevels: ALL_TLP })
      expect(someTlp).toEqual(noTlp)
      expect(allTlp).toEqual(noTlp)
    })

    it('output JSON contains no tlp markers', () => {
      const filters = toAnalyticsFilters(
        makeState({ tlpLevels: ALL_TLP, groupIds: [1] }),
      )
      const json = JSON.stringify(filters).toLowerCase()
      expect(json).not.toContain('tlp')
      expect(json).not.toContain('amber')
    })
  })
})

describe('toAttackMatrixQueryParams', () => {
  it('emits shared date + group params', () => {
    const params = toAttackMatrixQueryParams({
      date_from: '2026-01-01',
      date_to: '2026-04-18',
      group_id: [1, 3],
    })
    expect(params.get('date_from')).toBe('2026-01-01')
    expect(params.get('date_to')).toBe('2026-04-18')
    expect(params.getAll('group_id')).toEqual(['1', '3'])
  })

  it('emits top_n when provided', () => {
    const params = toAttackMatrixQueryParams({}, { top_n: 50 })
    expect(params.get('top_n')).toBe('50')
  })

  it('omits top_n when undefined (BE default applies)', () => {
    const params = toAttackMatrixQueryParams({})
    expect(params.has('top_n')).toBe(false)
  })

  it('never emits tlp even if smuggled through the filters bag', () => {
    const params = toAttackMatrixQueryParams({
      // @ts-expect-error — intentionally attempt to leak TLP
      tlp: 'AMBER',
      group_id: [2],
    })
    for (const key of params.keys()) {
      expect(key.toLowerCase()).not.toContain('tlp')
    }
    expect(params.getAll('group_id')).toEqual(['2'])
  })
})

describe('toTrendQueryParams', () => {
  it('emits shared date + group params without top_n', () => {
    const params = toTrendQueryParams({
      date_from: '2026-01-01',
      date_to: '2026-04-18',
      group_id: [1],
    })
    expect(params.get('date_from')).toBe('2026-01-01')
    expect(params.get('date_to')).toBe('2026-04-18')
    expect(params.getAll('group_id')).toEqual(['1'])
    expect(params.has('top_n')).toBe(false)
  })

  it('returns empty params for empty filters', () => {
    const params = toTrendQueryParams({})
    expect(params.toString()).toBe('')
  })
})

describe('toIncidentsTrendQueryParams (PR #23 §6.A C1)', () => {
  it('serializes group_by alongside the shared date + group params', () => {
    // Note: group_id canonicalization (sort ASC) lives in
    // `toAnalyticsFilters`, not in this serializer. Pass already-
    // canonicalized input to mirror what the hook layer feeds in.
    const params = toIncidentsTrendQueryParams(
      {
        date_from: '2026-01-01',
        date_to: '2026-04-18',
        group_id: [1, 3],
      },
      'motivation',
    )
    expect(params.get('group_by')).toBe('motivation')
    expect(params.get('date_from')).toBe('2026-01-01')
    expect(params.get('date_to')).toBe('2026-04-18')
    expect(params.getAll('group_id')).toEqual(['1', '3'])
  })

  it('serializes group_by=sector', () => {
    const params = toIncidentsTrendQueryParams({}, 'sector')
    expect(params.toString()).toBe('group_by=sector')
  })

  it('emits group_by even with no other filters', () => {
    const params = toIncidentsTrendQueryParams({}, 'motivation')
    expect(params.has('group_by')).toBe(true)
    expect(params.has('date_from')).toBe(false)
    expect(params.has('group_id')).toBe(false)
  })
})

describe('toGeoQueryParams', () => {
  it('emits shared date + group params', () => {
    const params = toGeoQueryParams({
      date_from: '2026-01-01',
      group_id: [3],
    })
    expect(params.get('date_from')).toBe('2026-01-01')
    expect(params.getAll('group_id')).toEqual(['3'])
  })

  it('still emits group_id even though BE treats it as no-op (schema-level)', () => {
    // Plan D2 documents group_id as a BE no-op for /geo, but the FE
    // still serializes it so a future BE change wiring the filter
    // does not require a FE change. This test pins that the FE
    // side does NOT drop the param optimistically.
    const params = toGeoQueryParams({ group_id: [3] })
    expect(params.getAll('group_id')).toEqual(['3'])
  })
})

// Static type-level contract — `AnalyticsFilters` carries no tlp
// field. Compiler error here = D4 violation.
const _typeContract: AnalyticsFilters = {
  date_from: '2026-01-01',
  date_to: '2026-04-18',
  group_id: [1, 2],
}
void _typeContract
