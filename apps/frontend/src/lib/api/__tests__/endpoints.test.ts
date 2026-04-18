import { describe, expect, it, vi } from 'vitest'

import {
  getDashboardSummary,
  getMe,
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
