import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api'
import { createQueryClient } from '../queryClient'
import { queryKeys } from '../queryKeys'

describe('createQueryClient', () => {
  it('returns a QueryClient with retry disabled by default', () => {
    const client = createQueryClient()
    const defaults = client.getDefaultOptions()
    expect(defaults.queries?.retry).toBe(false)
    expect(defaults.queries?.refetchOnWindowFocus).toBe(false)
  })

  it('onError sets me cache to null on ApiError 401', async () => {
    const client = createQueryClient()

    // Run a failing query that throws ApiError 401 — this exercises
    // the queryCache.onError path directly.
    const unrelatedKey = ['unrelated'] as const
    await client
      .fetchQuery({
        queryKey: unrelatedKey,
        queryFn: () => {
          throw new ApiError(401, { detail: 'expired' })
        },
      })
      .catch(() => {
        // expected — we want to observe the cache side-effect, not
        // the rethrown error
      })

    expect(client.getQueryData(queryKeys.me())).toBeNull()
  })

  it('onError does NOT touch me cache on non-401 ApiError', async () => {
    const client = createQueryClient()
    client.setQueryData(queryKeys.me(), { sub: 'x', email: 'e', roles: [] })

    await client
      .fetchQuery({
        queryKey: ['other'] as const,
        queryFn: () => {
          throw new ApiError(500, null)
        },
      })
      .catch(() => {})

    // The me cache survives a 500 — only 401 evicts identity.
    expect(client.getQueryData(queryKeys.me())).toEqual({
      sub: 'x',
      email: 'e',
      roles: [],
    })
  })

  it('onError does NOT touch me cache on non-ApiError failures (network, etc.)', async () => {
    const client = createQueryClient()
    client.setQueryData(queryKeys.me(), { sub: 'x', email: 'e', roles: [] })

    await client
      .fetchQuery({
        queryKey: ['other'] as const,
        queryFn: () => {
          throw new Error('ECONNREFUSED')
        },
      })
      .catch(() => {})

    expect(client.getQueryData(queryKeys.me())).toEqual({
      sub: 'x',
      email: 'e',
      roles: [],
    })
  })

  it('does not cascade-invalidate on 401 (avoid thundering herd)', async () => {
    const client = createQueryClient()
    // Seed a non-me query so we can observe whether it gets
    // invalidated/refetched.
    const seededData = { page: 1 }
    client.setQueryData(['actors'], seededData)
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')

    await client
      .fetchQuery({
        queryKey: ['other'] as const,
        queryFn: () => {
          throw new ApiError(401, null)
        },
      })
      .catch(() => {})

    // The 401 path must not call invalidateQueries — doing so
    // would cascade refetches of every authenticated query.
    expect(invalidateSpy).not.toHaveBeenCalled()
    // Other cached data survives the 401 (logout is the explicit
    // clear path; 401 just marks identity unauth).
    expect(client.getQueryData(['actors'])).toEqual(seededData)
  })
})
