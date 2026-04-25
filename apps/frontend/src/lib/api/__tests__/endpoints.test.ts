import { describe, expect, it, vi } from 'vitest'

import {
  getActorDetail,
  getActorReports,
  getDashboardSummary,
  getIncidentDetail,
  getMe,
  getReportDetail,
  getSimilarReports,
  listActors,
  listIncidents,
  listReports,
  logout,
} from '../endpoints'

describe('getMe', () => {
  it('GETs /api/v1/auth/me and parses the response', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          sub: 'abc-123',
          email: 'analyst@dprk.test',
          name: null,
          roles: ['analyst'],
        }),
        { status: 200 },
      ),
    )
    const user = await getMe()
    expect(user.sub).toBe('abc-123')
    expect(user.roles).toEqual(['analyst'])

    const [url, init] = fetchSpy.mock.calls[0]
    expect(String(url)).toContain('/api/v1/auth/me')
    expect(init!.method ?? 'GET').toBe('GET')
  })
})

describe('logout', () => {
  it('POSTs /api/v1/auth/logout and resolves null for 204', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(null, { status: 204 }),
    )
    const result = await logout()
    expect(result).toBeNull()

    const [url, init] = fetchSpy.mock.calls[0]
    expect(String(url)).toContain('/api/v1/auth/logout')
    expect(init!.method).toBe('POST')
  })
})

describe('getDashboardSummary', () => {
  const summary = {
    total_reports: 1,
    total_incidents: 2,
    total_actors: 3,
    reports_by_year: [],
    incidents_by_motivation: [],
    top_groups: [],
    top_sectors: [],
    top_sources: [],
  }

  it('GETs /api/v1/dashboard/summary with no querystring when filters empty', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(summary), { status: 200 }),
    )
    const parsed = await getDashboardSummary({})
    expect(parsed.total_reports).toBe(1)

    const [url] = fetchSpy.mock.calls[0]
    const asString = String(url)
    expect(asString).toContain('/api/v1/dashboard/summary')
    expect(asString).not.toContain('?')
  })

  it('passes date_from / date_to / repeated group_id', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(summary), { status: 200 }),
    )
    await getDashboardSummary({
      date_from: '2026-01-01',
      date_to: '2026-04-18',
      group_id: [1, 3],
    })
    const [url] = fetchSpy.mock.calls[0]
    const parsed = new URL(String(url))
    expect(parsed.searchParams.get('date_from')).toBe('2026-01-01')
    expect(parsed.searchParams.get('date_to')).toBe('2026-04-18')
    expect(parsed.searchParams.getAll('group_id')).toEqual(['1', '3'])
  })

  it('never emits a tlp* query param (D5 — type layer already blocks but runtime pin is a defensive belt)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(summary), { status: 200 }),
    )
    // Smuggle a TLP-shaped key via cast — the type layer would
    // normally prevent this; here we exercise the runtime path.
    await getDashboardSummary({
      group_id: [1],
      // @ts-expect-error — intentionally malformed
      tlp: 'AMBER',
    })
    const [url] = vi.mocked(global.fetch).mock.calls[0]
    const parsed = new URL(String(url))
    for (const key of parsed.searchParams.keys()) {
      expect(key.toLowerCase()).not.toContain('tlp')
    }
  })
})

describe('listActors', () => {
  const actorsResp = {
    items: [
      {
        id: 3,
        name: 'Lazarus Group',
        mitre_intrusion_set_id: 'G0032',
        aka: ['APT38'],
        description: null,
        codenames: [],
      },
    ],
    limit: 50,
    offset: 0,
    total: 1,
  }

  it('GETs /api/v1/actors with no querystring when pagination empty', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(actorsResp), { status: 200 }),
    )
    const r = await listActors()
    expect(r.items[0].name).toBe('Lazarus Group')
    const asString = String(fetchSpy.mock.calls[0][0])
    expect(asString).toContain('/api/v1/actors')
    expect(asString).not.toContain('?')
  })

  it('passes limit + offset on the wire', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(actorsResp), { status: 200 }),
    )
    await listActors({ limit: 20, offset: 40 })
    const parsed = new URL(String(fetchSpy.mock.calls[0][0]))
    expect(parsed.searchParams.get('limit')).toBe('20')
    expect(parsed.searchParams.get('offset')).toBe('40')
  })

  it('surfaces 429 as ApiError.status=429', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ error: 'rate_limit_exceeded', message: '60 per 1 minute' }),
        { status: 429 },
      ),
    )
    try {
      await listActors()
      expect.fail('expected listActors() to throw on 429')
    } catch (err) {
      // Imported from the api module to keep the test typed.
      const { ApiError } = await import('../../api')
      expect(err).toBeInstanceOf(ApiError)
      expect((err as InstanceType<typeof ApiError>).status).toBe(429)
    }
  })
})

describe('listReports', () => {
  const reportsResp = {
    items: [
      {
        id: 42,
        title: 'Report',
        url: 'https://example.test',
        url_canonical: 'https://example.test',
        published: '2026-03-15',
      },
    ],
    next_cursor: null,
  }

  it('GETs /api/v1/reports with date_from/date_to/cursor/limit', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(reportsResp), { status: 200 }),
    )
    await listReports(
      { date_from: '2026-01-01', date_to: '2026-04-18' },
      { cursor: 'abc', limit: 50 },
    )
    const parsed = new URL(String(fetchSpy.mock.calls[0][0]))
    expect(parsed.searchParams.get('date_from')).toBe('2026-01-01')
    expect(parsed.searchParams.get('date_to')).toBe('2026-04-18')
    expect(parsed.searchParams.get('cursor')).toBe('abc')
    expect(parsed.searchParams.get('limit')).toBe('50')
  })

  it('never sends group_id (endpoint contract audit pin)', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(reportsResp), { status: 200 }),
    )
    // Even if a future caller tries to smuggle group_id via a cast,
    // the transform has no code path that emits it. Belt + type.
    // @ts-expect-error — intentionally malformed input
    await listReports({ date_from: '2026-01-01', group_id: [1] }, {})
    const parsed = new URL(String(fetchSpy.mock.calls[0][0]))
    expect(parsed.searchParams.has('group_id')).toBe(false)
  })
})

describe('listIncidents', () => {
  const incidentsResp = {
    items: [
      {
        id: 18,
        title: 'Ronin bridge',
        motivations: ['financial'],
        sectors: ['crypto'],
        countries: ['VN'],
      },
    ],
    next_cursor: null,
  }

  it('GETs /api/v1/incidents with date_from/date_to/cursor', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(incidentsResp), { status: 200 }),
    )
    await listIncidents({ date_from: '2026-01-01' }, { cursor: 'xyz' })
    const parsed = new URL(String(fetchSpy.mock.calls[0][0]))
    expect(parsed.searchParams.get('date_from')).toBe('2026-01-01')
    expect(parsed.searchParams.get('cursor')).toBe('xyz')
  })
})

// ---------------------------------------------------------------------------
// Detail + similar endpoints — PR #14 Group D
// ---------------------------------------------------------------------------

describe('getReportDetail', () => {
  const body = {
    id: 42,
    title: 'Lazarus targets SK crypto exchanges',
    url: 'https://mandiant.com/blog/lazarus-2026q1',
    url_canonical: 'https://mandiant.com/blog/lazarus-2026q1',
    published: '2026-03-15',
    source_id: 7,
    source_name: 'Mandiant',
    lang: 'en',
    tlp: 'WHITE',
    summary: null,
    reliability: null,
    credibility: null,
    tags: [],
    codenames: [],
    techniques: [],
    linked_incidents: [],
  }

  it('GETs /api/v1/reports/{id} with no querystring', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(body), { status: 200 }),
    )
    await getReportDetail(42)
    const url = new URL(String(fetchSpy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/reports/42')
    expect(url.search).toBe('')
  })
})

describe('getIncidentDetail', () => {
  const body = {
    id: 18,
    reported: null,
    title: 'Ronin bridge',
    description: null,
    est_loss_usd: null,
    attribution_confidence: null,
    motivations: [],
    sectors: [],
    countries: [],
    linked_reports: [],
  }

  it('GETs /api/v1/incidents/{id} with no querystring', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(body), { status: 200 }),
    )
    await getIncidentDetail(18)
    const url = new URL(String(fetchSpy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/incidents/18')
    expect(url.search).toBe('')
  })
})

describe('getActorDetail', () => {
  const body = {
    id: 3,
    name: 'Lazarus Group',
    mitre_intrusion_set_id: 'G0032',
    aka: [],
    description: null,
    codenames: [],
  }

  it('GETs /api/v1/actors/{id} with no querystring', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(body), { status: 200 }),
    )
    await getActorDetail(3)
    const url = new URL(String(fetchSpy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/actors/3')
    expect(url.search).toBe('')
  })
})

describe('getSimilarReports', () => {
  const empty = { items: [] }

  it('GETs /api/v1/reports/{id}/similar with default k=10', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(empty), { status: 200 }),
    )
    await getSimilarReports(42)
    const url = new URL(String(fetchSpy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/reports/42/similar')
    expect(url.searchParams.get('k')).toBe('10')
  })

  it('sends caller-supplied k on the querystring', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(empty), { status: 200 }),
    )
    await getSimilarReports(42, 25)
    const url = new URL(String(fetchSpy.mock.calls[0][0]))
    expect(url.searchParams.get('k')).toBe('25')
  })

  // D10 empty contract: helper returns {items: []} without throwing.
  it('resolves the D10 empty contract verbatim', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(empty), { status: 200 }),
    )
    const res = await getSimilarReports(42)
    expect(res).toEqual({ items: [] })
  })
})

// PR #15 Group D — getActorReports endpoint helper. Plan D1 + D2 +
// D9 lock pinned: path contains actorId, querystring is date/cursor/
// limit only, response reuses ReportListResponse envelope.
describe('getActorReports', () => {
  const populated = {
    items: [
      {
        id: 999050,
        title: 'fixture',
        url: 'https://x.test/1',
        url_canonical: 'https://x.test/1',
        published: '2026-03-15',
        source_id: 1,
        source_name: 'Vendor',
        lang: 'en',
        tlp: 'WHITE',
      },
    ],
    next_cursor: null,
  }

  const empty = { items: [], next_cursor: null }

  it('GETs /api/v1/actors/{id}/reports with no querystring when no filters/pagination', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(empty), { status: 200 }),
    )
    await getActorReports(999003)
    const url = new URL(String(fetchSpy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/actors/999003/reports')
    expect(url.search).toBe('')
  })

  it('sends date_from + date_to + cursor + limit on the querystring', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(populated), { status: 200 }),
    )
    await getActorReports(
      999003,
      { date_from: '2026-01-01', date_to: '2026-12-31' },
      { cursor: 'MjAyNi0wMy0xNXw5OTkwNTA', limit: 50 },
    )
    const url = new URL(String(fetchSpy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/actors/999003/reports')
    expect(url.searchParams.get('date_from')).toBe('2026-01-01')
    expect(url.searchParams.get('date_to')).toBe('2026-12-31')
    expect(url.searchParams.get('cursor')).toBe(
      'MjAyNi0wMy0xNXw5OTkwNTA',
    )
    expect(url.searchParams.get('limit')).toBe('50')
  })

  // D9 envelope — response is ReportListResponse-shaped. No total,
  // no limit echo; Zod strips any such leak silently.
  it('resolves the BE envelope verbatim ({items, next_cursor} only)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(populated), { status: 200 }),
    )
    const res = await getActorReports(999003)
    expect(res.items).toHaveLength(1)
    expect(res.items[0].id).toBe(999050)
    expect(res.next_cursor).toBeNull()
    expect(Object.keys(res).sort()).toEqual(['items', 'next_cursor'])
  })

  // D15(b/c/d) — 200 + empty envelope passes through to the panel.
  it('resolves the D15 empty contract (panel-friendly shape)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(empty), { status: 200 }),
    )
    const res = await getActorReports(999004)
    expect(res).toEqual({ items: [], next_cursor: null })
  })

  // D2 lock — wire surface is path-param + date + cursor + limit
  // only. No TLP / groupIds / q / tag / source fields reach the
  // querystring because `ActorReportsFilters` has no such fields.
  it('never emits TLP / groupIds / q / tag / source on the wire', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(empty), { status: 200 }),
    )
    await getActorReports(
      999003,
      // @ts-expect-error — ActorReportsFilters has no such fields;
      // the runtime serializer MUST ignore them even if a caller bypasses
      // the type system.
      { tlpLevels: ['AMBER'], groupIds: [3], q: 'x', tag: ['t'], source: ['s'] },
      {},
    )
    const url = new URL(String(fetchSpy.mock.calls[0][0]))
    expect(url.search).toBe('')
  })
})
