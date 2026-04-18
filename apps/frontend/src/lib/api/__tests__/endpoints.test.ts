import { describe, expect, it, vi } from 'vitest'

import { getDashboardSummary, getMe, logout } from '../endpoints'

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
