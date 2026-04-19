import { describe, expect, it } from 'vitest'

import {
  toActorListQueryParams,
  toActorReportsFilters,
  toActorReportsQueryParams,
  toIncidentListFilters,
  toIncidentListQueryParams,
  toReportListFilters,
  toReportListQueryParams,
} from '../listFilters'
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

describe('toReportListFilters', () => {
  it('returns empty when no date range set', () => {
    expect(toReportListFilters(makeState())).toEqual({})
  })

  it('renames dateFrom/dateTo to BE wire names', () => {
    const filters = toReportListFilters(
      makeState({ dateFrom: '2026-01-01', dateTo: '2026-04-18' }),
    )
    expect(filters).toEqual({ date_from: '2026-01-01', date_to: '2026-04-18' })
  })

  // D7 + endpoint audit — /reports accepts q/tag/source/date_*/cursor/
  // limit. It does NOT accept group_id. The filter bar's groupIds
  // must never leak into the reports list payload — wiring that
  // silently sends it would waste bandwidth, pointlessly vary the
  // cache key, and hide a contract bug behind FastAPI's default-drop
  // behavior for unknown kwargs.
  it('groupIds are never included in the output (type layer + runtime belt)', () => {
    const filters = toReportListFilters(
      makeState({
        dateFrom: '2026-01-01',
        groupIds: [1, 2, 3],
        tlpLevels: ALL_TLP,
      }),
    )
    const json = JSON.stringify(filters).toLowerCase()
    expect(json).not.toContain('group')
    expect(json).not.toContain('tlp')
    // And identical output whether groupIds/tlpLevels are populated
    // — the transform must only see dateFrom / dateTo.
    const without = toReportListFilters(makeState({ dateFrom: '2026-01-01' }))
    expect(filters).toEqual(without)
  })
})

describe('toIncidentListFilters', () => {
  it('renames dateFrom/dateTo', () => {
    const filters = toIncidentListFilters(
      makeState({ dateFrom: '2026-01-01', dateTo: '2026-04-18' }),
    )
    expect(filters).toEqual({ date_from: '2026-01-01', date_to: '2026-04-18' })
  })

  it('groupIds + TLP are never included', () => {
    const filters = toIncidentListFilters(
      makeState({
        dateFrom: '2026-01-01',
        groupIds: [1, 2, 3],
        tlpLevels: ALL_TLP,
      }),
    )
    const without = toIncidentListFilters(makeState({ dateFrom: '2026-01-01' }))
    expect(filters).toEqual(without)
  })
})

describe('toReportListQueryParams', () => {
  it('composes date_from / date_to / cursor / limit', () => {
    const params = toReportListQueryParams(
      { date_from: '2026-01-01', date_to: '2026-04-18' },
      { cursor: 'abc', limit: 50 },
    )
    expect(params.get('date_from')).toBe('2026-01-01')
    expect(params.get('date_to')).toBe('2026-04-18')
    expect(params.get('cursor')).toBe('abc')
    expect(params.get('limit')).toBe('50')
  })

  it('omits pagination keys when undefined', () => {
    const params = toReportListQueryParams({})
    expect(params.toString()).toBe('')
  })

  it('never emits group_id or tlp*', () => {
    const params = toReportListQueryParams(
      // @ts-expect-error — exercise runtime belt
      { date_from: '2026-01-01', group_id: [1], tlp: 'AMBER' },
      { limit: 50 },
    )
    for (const key of params.keys()) {
      expect(key).not.toBe('group_id')
      expect(key.toLowerCase()).not.toContain('tlp')
    }
  })
})

describe('toIncidentListQueryParams', () => {
  it('composes date_from / date_to / cursor / limit', () => {
    const params = toIncidentListQueryParams(
      { date_from: '2026-01-01' },
      { cursor: 'xyz' },
    )
    expect(params.get('date_from')).toBe('2026-01-01')
    expect(params.get('cursor')).toBe('xyz')
  })
})

describe('toActorListQueryParams', () => {
  it('emits limit + offset', () => {
    const params = toActorListQueryParams({ limit: 20, offset: 40 })
    expect(params.get('limit')).toBe('20')
    expect(params.get('offset')).toBe('40')
  })

  it('empty pagination → empty querystring (BE defaults apply)', () => {
    expect(toActorListQueryParams({}).toString()).toBe('')
  })

  // /actors has no date/group/tlp filter surface. Types don't even
  // name those fields. This test is the defensive belt: make sure
  // passing any FilterBar state to the actor transform is a no-op.
  it('ignores FilterBar state entirely — actors has no filter contract', () => {
    // @ts-expect-error — FilterState fields don't belong here
    const params = toActorListQueryParams({
      limit: 50,
      dateFrom: '2026-01-01',
      groupIds: [3],
      tlpLevels: ['AMBER'],
    })
    expect(params.get('limit')).toBe('50')
    expect(params.has('date_from')).toBe(false)
    expect(params.has('group_id')).toBe(false)
    for (const key of params.keys()) {
      expect(key.toLowerCase()).not.toContain('tlp')
    }
  })
})

// PR #15 Group D — ActorReportsFilters + query-param serializer.
describe('toActorReportsQueryParams (PR #15 D2 minimal filter)', () => {
  it('emits date_from + date_to + cursor + limit when all present', () => {
    const params = toActorReportsQueryParams(
      { date_from: '2026-01-01', date_to: '2026-12-31' },
      { cursor: 'MjAyNi0wMy0xNXw5OTkwNTA', limit: 50 },
    )
    expect(params.get('date_from')).toBe('2026-01-01')
    expect(params.get('date_to')).toBe('2026-12-31')
    expect(params.get('cursor')).toBe('MjAyNi0wMy0xNXw5OTkwNTA')
    expect(params.get('limit')).toBe('50')
  })

  it('empty filters + empty pagination → empty querystring (BE defaults apply)', () => {
    expect(toActorReportsQueryParams({}, {}).toString()).toBe('')
  })

  // D2 filter lock — no q / tag / source / tlp / groupIds reach the
  // wire because `ActorReportsFilters` has no such fields. Passing
  // them forces a compile error AND a runtime drop.
  it('ignores FilterBar state outside date range — D2 lock', () => {
    // @ts-expect-error — FilterState fields don't belong here
    const params = toActorReportsQueryParams(
      {
        date_from: '2026-01-01',
        tlpLevels: ['AMBER'],
        groupIds: [3],
        q: 'lazarus',
        tag: ['ransomware'],
        source: ['mandiant'],
      },
      {},
    )
    expect(params.get('date_from')).toBe('2026-01-01')
    expect(params.has('group_id')).toBe(false)
    expect(params.has('q')).toBe(false)
    expect(params.has('tag')).toBe(false)
    expect(params.has('source')).toBe(false)
    for (const key of params.keys()) {
      expect(key.toLowerCase()).not.toContain('tlp')
    }
  })

  it('toActorReportsFilters mirrors pickDateRange — dateFrom/dateTo only', () => {
    // @ts-expect-error — extra FilterState fields must not pollute the result
    const out = toActorReportsFilters({
      dateFrom: '2026-01-01',
      dateTo: '2026-12-31',
      groupIds: [3],
      tlpLevels: ['AMBER'],
    })
    expect(out).toEqual({ date_from: '2026-01-01', date_to: '2026-12-31' })
    expect(Object.keys(out).sort()).toEqual(['date_from', 'date_to'])
  })
})
