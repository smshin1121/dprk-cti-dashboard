import { describe, expect, it, vi } from 'vitest'

import { getMe, logout } from '../endpoints'

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
