import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { ApiError, apiGet, apiPost } from '../api'

function mockFetchJson(status: number, body: unknown): void {
  vi.spyOn(global, 'fetch').mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

function mockFetchEmpty(status: number): void {
  vi.spyOn(global, 'fetch').mockResolvedValue(new Response(null, { status }))
}

describe('ApiError', () => {
  it('carries status + detail', () => {
    const err = new ApiError(404, { error: 'not_found' })
    expect(err).toBeInstanceOf(Error)
    expect(err.status).toBe(404)
    expect(err.detail).toEqual({ error: 'not_found' })
    expect(err.name).toBe('ApiError')
    expect(err.message).toBe('API error 404')
  })

  it('accepts a custom message', () => {
    const err = new ApiError(500, null, 'oops')
    expect(err.message).toBe('oops')
  })
})

describe('apiGet', () => {
  const schema = z.object({ ok: z.boolean() })

  it('parses a 2xx JSON body through the Zod schema', async () => {
    mockFetchJson(200, { ok: true })
    const result = await apiGet('/test', schema)
    expect(result).toEqual({ ok: true })
  })

  it('includes credentials on every request', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    )
    await apiGet('/test', schema)
    const init = fetchSpy.mock.calls[0][1]!
    expect(init.credentials).toBe('include')
  })

  it('throws ApiError with status + parsed detail on 4xx', async () => {
    mockFetchJson(403, { error: 'forbidden', message: 'no' })
    await expect(apiGet('/test', schema)).rejects.toMatchObject({
      status: 403,
      detail: { error: 'forbidden', message: 'no' },
    })
  })

  it('throws ApiError with null detail when error body is not JSON', async () => {
    mockFetchEmpty(503)
    await expect(apiGet('/test', schema)).rejects.toMatchObject({
      status: 503,
      detail: null,
    })
  })

  it('propagates Zod parse errors on contract drift', async () => {
    mockFetchJson(200, { ok: 'not-a-boolean' })
    await expect(apiGet('/test', schema)).rejects.toThrow(/boolean/i)
  })

  it('forwards the abort signal', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    )
    const ctrl = new AbortController()
    await apiGet('/test', schema, ctrl.signal)
    expect(fetchSpy.mock.calls[0][1]!.signal).toBe(ctrl.signal)
  })
})

describe('apiPost', () => {
  it('sends JSON body with Content-Type header and returns parsed response', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ id: 1 }), { status: 201 }),
    )
    const schema = z.object({ id: z.number() })
    const result = await apiPost('/things', { name: 'x' }, schema)
    expect(result).toEqual({ id: 1 })

    const init = fetchSpy.mock.calls[0][1]!
    expect(init.method).toBe('POST')
    expect(init.body).toBe(JSON.stringify({ name: 'x' }))
    expect((init.headers as Record<string, string>)['Content-Type']).toBe(
      'application/json',
    )
  })

  it('returns null for 204 endpoints when schema is explicitly null', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(new Response(null, { status: 204 }))
    const result = await apiPost('/logout', undefined, null)
    expect(result).toBeNull()
  })

  it('does not set Content-Type when body is undefined', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(null, { status: 204 }),
    )
    await apiPost('/logout', undefined, null)
    const init = fetchSpy.mock.calls[0][1]!
    const headers = (init.headers ?? {}) as Record<string, string>
    expect(headers['Content-Type']).toBeUndefined()
  })
})
