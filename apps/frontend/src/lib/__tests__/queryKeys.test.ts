import { describe, expect, it } from 'vitest'

import { queryKeys } from '../queryKeys'
import { toDashboardSummaryFilters } from '../dashboardFilters'
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

describe('queryKeys.me', () => {
  it('is stable across calls (tuple identity by structural equality)', () => {
    expect(queryKeys.me()).toEqual(queryKeys.me())
  })
})

describe('queryKeys.dashboardSummary', () => {
  it('uses the documented ["dashboard","summary", filters] shape', () => {
    const key = queryKeys.dashboardSummary({})
    expect(key[0]).toBe('dashboard')
    expect(key[1]).toBe('summary')
    expect(key[2]).toEqual({})
  })

  it('is structurally equal for identical filter objects', () => {
    const a = queryKeys.dashboardSummary({ date_from: '2026-01-01', group_id: [3] })
    const b = queryKeys.dashboardSummary({ date_from: '2026-01-01', group_id: [3] })
    expect(a).toEqual(b)
  })

  it('differs when filters change', () => {
    const a = queryKeys.dashboardSummary({ group_id: [3] })
    const b = queryKeys.dashboardSummary({ group_id: [5] })
    expect(a).not.toEqual(b)
  })

  // Codex P2 regression — group_id sets are unordered on the BE, so
  // the cache key MUST be the same regardless of UI toggle order.
  // Without canonicalization in toDashboardSummaryFilters, picking
  // groups [1,3] vs [3,1] in the UI produced two distinct cache
  // entries for the same logical filter.
  it('same group set toggled in different order produces equal cache keys', () => {
    const a = queryKeys.dashboardSummary(
      toDashboardSummaryFilters(makeState({ groupIds: [1, 3] })),
    )
    const b = queryKeys.dashboardSummary(
      toDashboardSummaryFilters(makeState({ groupIds: [3, 1] })),
    )
    expect(a).toEqual(b)
  })

  // D5 contract at the cache layer — if TLP ever reaches the cache
  // key, toggling a TLP checkbox would re-fetch the same data under
  // a different key, breaking cache economy AND leaking the UI-only
  // dimension into the server-state boundary. Type system blocks the
  // insertion; this runtime test catches any accidental `any` cast.
  it('TLP selection does not affect the cache key (D5 + D10 lock)', () => {
    const base = makeState({
      dateFrom: '2026-01-01',
      dateTo: '2026-04-18',
      groupIds: [3, 5],
    })
    const noTlp = queryKeys.dashboardSummary(
      toDashboardSummaryFilters({ ...base, tlpLevels: [] }),
    )
    const allTlp = queryKeys.dashboardSummary(
      toDashboardSummaryFilters({ ...base, tlpLevels: ALL_TLP }),
    )
    expect(allTlp).toEqual(noTlp)
  })

  it('cache key JSON contains no tlp markers', () => {
    const key = queryKeys.dashboardSummary(
      toDashboardSummaryFilters(makeState({ tlpLevels: ALL_TLP, groupIds: [1] })),
    )
    const json = JSON.stringify(key).toLowerCase()
    expect(json).not.toContain('tlp')
    expect(json).not.toContain('amber')
  })
})

describe('queryKeys.actors', () => {
  it('uses pagination shape for the key', () => {
    const key = queryKeys.actors({ limit: 50, offset: 0 })
    expect(key[0]).toBe('actors')
    expect(key[1]).toEqual({ limit: 50, offset: 0 })
  })

  it('keys for different offsets differ', () => {
    expect(queryKeys.actors({ offset: 0 })).not.toEqual(
      queryKeys.actors({ offset: 50 }),
    )
  })
})

describe('queryKeys.reports', () => {
  it('shape is [reports, filters, pagination]', () => {
    const key = queryKeys.reports({ date_from: '2026-01-01' }, { cursor: 'c' })
    expect(key[0]).toBe('reports')
    expect(key[1]).toEqual({ date_from: '2026-01-01' })
    expect(key[2]).toEqual({ cursor: 'c' })
  })

  it('filters + cursor change produces different keys', () => {
    const a = queryKeys.reports({ date_from: '2026-01-01' }, { cursor: 'a' })
    const b = queryKeys.reports({ date_from: '2026-01-01' }, { cursor: 'b' })
    expect(a).not.toEqual(b)
  })
})

describe('queryKeys.incidents', () => {
  it('shape is [incidents, filters, pagination]', () => {
    const key = queryKeys.incidents({ date_from: '2026-01-01' })
    expect(key[0]).toBe('incidents')
  })
})

// ---------------------------------------------------------------------------
// Detail + similar keys — PR #14 Group D (plan D1 + D8 + D11)
// ---------------------------------------------------------------------------
//
// These keys carry ONLY the path-param id (and k for similar). The
// hooks built on them don't subscribe to `useFilterStore`, so
// filter state cannot enter these cache slots — enforced both
// structurally (no filter import in the hook files) and at the
// type boundary (`reportDetail(id: number)` has no filter arg).

describe('queryKeys.reportDetail', () => {
  it('uses the documented ["reports", "detail", id] shape', () => {
    const key = queryKeys.reportDetail(42)
    expect(key).toEqual(['reports', 'detail', 42])
  })

  it('different ids produce different keys', () => {
    expect(queryKeys.reportDetail(1)).not.toEqual(queryKeys.reportDetail(2))
  })

  it('cache key JSON contains no filter markers', () => {
    const json = JSON.stringify(queryKeys.reportDetail(42)).toLowerCase()
    expect(json).not.toContain('tlp')
    expect(json).not.toContain('date_from')
    expect(json).not.toContain('group_id')
  })
})

describe('queryKeys.incidentDetail', () => {
  it('uses the documented ["incidents", "detail", id] shape', () => {
    const key = queryKeys.incidentDetail(18)
    expect(key).toEqual(['incidents', 'detail', 18])
  })

  it('does not collide with reports detail key for the same id', () => {
    expect(queryKeys.incidentDetail(42)).not.toEqual(queryKeys.reportDetail(42))
  })
})

describe('queryKeys.actorDetail', () => {
  it('uses the documented ["actors", "detail", id] shape', () => {
    const key = queryKeys.actorDetail(3)
    expect(key).toEqual(['actors', 'detail', 3])
  })
})

describe('queryKeys.similarReports', () => {
  it('uses the documented ["reports", id, "similar", k] shape', () => {
    const key = queryKeys.similarReports(42, 10)
    expect(key).toEqual(['reports', 42, 'similar', 10])
  })

  // D8 cache-key lock — (report_id, k) matches BE Redis key exactly.
  // Different k opens a fresh cache slot on both sides.
  it('different k values produce different keys for same report', () => {
    expect(queryKeys.similarReports(42, 10)).not.toEqual(
      queryKeys.similarReports(42, 20),
    )
  })

  it('different report_ids produce different keys for same k', () => {
    expect(queryKeys.similarReports(42, 10)).not.toEqual(
      queryKeys.similarReports(43, 10),
    )
  })

  it('does not collide with reportDetail key when id=k shape confusion', () => {
    expect(queryKeys.similarReports(10, 10)).not.toEqual(
      queryKeys.reportDetail(10),
    )
  })

  it('cache key JSON contains no filter markers', () => {
    const json = JSON.stringify(queryKeys.similarReports(42, 10)).toLowerCase()
    expect(json).not.toContain('tlp')
    expect(json).not.toContain('date_from')
    expect(json).not.toContain('group_id')
  })
})

describe('queryKeys.analyticsIncidentsTrend (PR #23 §6.A C1)', () => {
  const emptyFilters = {}
  const dateFilters = { date_from: '2026-01-01', date_to: '2026-04-18' }

  it('uses the documented ["analytics", "incidents_trend", groupBy, filters] shape', () => {
    const key = queryKeys.analyticsIncidentsTrend(emptyFilters, 'motivation')
    expect(key).toEqual(['analytics', 'incidents_trend', 'motivation', emptyFilters])
  })

  // Critical — without `groupBy` in the key, switching between
  // MotivationStackedArea and SectorStackedArea would flash stale
  // axis data from React Query's cache. Pin per-axis isolation.
  it('motivation and sector axes produce different keys for same filters', () => {
    expect(
      queryKeys.analyticsIncidentsTrend(emptyFilters, 'motivation'),
    ).not.toEqual(
      queryKeys.analyticsIncidentsTrend(emptyFilters, 'sector'),
    )
  })

  it('different filter inputs produce different keys for same axis', () => {
    expect(
      queryKeys.analyticsIncidentsTrend(emptyFilters, 'motivation'),
    ).not.toEqual(
      queryKeys.analyticsIncidentsTrend(dateFilters, 'motivation'),
    )
  })

  it('does not collide with analyticsTrend key for same filters (different fact tables)', () => {
    expect(
      queryKeys.analyticsIncidentsTrend(dateFilters, 'motivation'),
    ).not.toEqual(queryKeys.analyticsTrend(dateFilters))
  })

  it('cache key JSON contains no tlp marker (D5 isolation)', () => {
    const json = JSON.stringify(
      queryKeys.analyticsIncidentsTrend(dateFilters, 'sector'),
    ).toLowerCase()
    expect(json).not.toContain('tlp')
  })
})

describe('queryKeys.actorReports (PR #15 Group D)', () => {
  const emptyFilters = {}
  const dateFilters = { date_from: '2026-01-01', date_to: '2026-12-31' }

  it('uses the documented ["actors", id, "reports", filters, pagination] shape', () => {
    const key = queryKeys.actorReports(999003, emptyFilters, {})
    expect(key).toEqual(['actors', 999003, 'reports', {}, {}])
  })

  // D13 cache-key scope lock — key carries (actorId, filters,
  // pagination) only.
  it('different actorIds produce different keys', () => {
    expect(queryKeys.actorReports(1, emptyFilters, {})).not.toEqual(
      queryKeys.actorReports(2, emptyFilters, {}),
    )
  })

  it('different filters produce different keys for same actorId', () => {
    expect(queryKeys.actorReports(999003, emptyFilters, {})).not.toEqual(
      queryKeys.actorReports(999003, dateFilters, {}),
    )
  })

  it('different cursor/limit produce different keys', () => {
    expect(
      queryKeys.actorReports(999003, emptyFilters, { cursor: 'abc' }),
    ).not.toEqual(
      queryKeys.actorReports(999003, emptyFilters, { cursor: 'xyz' }),
    )
    expect(
      queryKeys.actorReports(999003, emptyFilters, { limit: 10 }),
    ).not.toEqual(
      queryKeys.actorReports(999003, emptyFilters, { limit: 50 }),
    )
  })

  // D2 / D13 filter-scope lock — no tlp, no groupIds, no q/tag/source.
  // ActorReportsFilters type has no such fields by construction; this
  // runtime test is the defensive belt against a future FilterBar
  // widening that would inadvertently pollute the cache key.
  it('cache key JSON contains no filter-store markers', () => {
    const key = queryKeys.actorReports(999003, dateFilters, {
      cursor: 'abc',
      limit: 50,
    })
    const json = JSON.stringify(key).toLowerCase()
    expect(json).not.toContain('tlp')
    expect(json).not.toContain('group_id')
    expect(json).not.toContain('groupids')
    expect(json).not.toContain('"q"')
    expect(json).not.toContain('"tag"')
    expect(json).not.toContain('"source"')
  })

  // D2 — key only ever contains actorId + date range + cursor +
  // limit. This test introspects every leaf string in the key to
  // catch a future schema widening at the contract layer.
  it('key leaf strings are exactly {date_from, date_to, cursor, limit} (order-independent)', () => {
    const key = queryKeys.actorReports(999003, dateFilters, {
      cursor: 'abc',
      limit: 50,
    })
    // key = ['actors', 999003, 'reports', filters, pagination]
    const filters = key[3] as Record<string, string>
    const pagination = key[4] as Record<string, string | number>
    const filterKeys = Object.keys(filters).sort()
    const paginationKeys = Object.keys(pagination).sort()
    expect(filterKeys).toEqual(['date_from', 'date_to'])
    expect(paginationKeys).toEqual(['cursor', 'limit'])
  })

  it('does not collide with actorDetail key', () => {
    expect(queryKeys.actorReports(999003, emptyFilters, {})).not.toEqual(
      queryKeys.actorDetail(999003),
    )
  })
})

// ---------------------------------------------------------------------------
// PR #17 Group D — queryKeys.searchHits scope lock
// ---------------------------------------------------------------------------
//
// Review criterion #3 for Group D: the /search cache key must
// contain EXACTLY `(q, filters)` where `filters` is the 3-key
// whitelist `{date_from?, date_to?, limit?}` — no tlp / groupIds /
// tag / source / cursor / anything else. Pinned at runtime below;
// the type layer (`SearchFilters`) backs it structurally.

describe('queryKeys.searchHits — PR #17 Group D', () => {
  it('returns a stable readonly key structure ["search", q, filters]', () => {
    const key = queryKeys.searchHits('lazarus', { date_from: '2026-03-01' })
    expect(key.length).toBe(3)
    expect(key[0]).toBe('search')
    expect(key[1]).toBe('lazarus')
    expect(key[2]).toEqual({ date_from: '2026-03-01' })
  })

  it('filters slot contains ONLY {date_from?, date_to?, limit?}', () => {
    const key = queryKeys.searchHits('lazarus', {
      date_from: '2026-03-01',
      date_to: '2026-03-31',
      limit: 10,
    })
    const filters = key[2] as Record<string, unknown>
    expect(Object.keys(filters).sort()).toEqual([
      'date_from',
      'date_to',
      'limit',
    ])
    // TLP / groupIds / tag / source / cursor must NOT be present —
    // the type signature forbids them, so a runtime-injected key
    // would only slip through via `as any` casting. The regression
    // this pins: if a future edit widens `SearchFilters`, we want
    // it to flip this assertion visibly.
    for (const forbidden of [
      'tlp',
      'group_id',
      'group_ids',
      'tag',
      'source',
      'cursor',
      'offset',
    ]) {
      expect(filters).not.toHaveProperty(forbidden)
    }
  })

  it('identical post-debounce q + filters produce equal keys (share cache slot)', () => {
    const a = queryKeys.searchHits('lazarus', { limit: 10 })
    const b = queryKeys.searchHits('lazarus', { limit: 10 })
    expect(a).toEqual(b)
  })

  it('different q opens a new cache slot', () => {
    expect(
      queryKeys.searchHits('lazarus', {}),
    ).not.toEqual(queryKeys.searchHits('kimsuky', {}))
  })

  it('different limit opens a new cache slot', () => {
    expect(
      queryKeys.searchHits('lazarus', { limit: 10 }),
    ).not.toEqual(queryKeys.searchHits('lazarus', { limit: 20 }))
  })

  it('does not collide with the actorReports key', () => {
    expect(queryKeys.searchHits('lazarus', {})).not.toEqual(
      queryKeys.actorReports(999003, {}, {}),
    )
  })
})
