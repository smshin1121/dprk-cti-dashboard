import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { queryKeys } from '../../../lib/queryKeys'
import { useAuth } from '../useAuth'

function wrapperWith(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useAuth', () => {
  it('reports loading on initial render', () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => {}), // never resolves
    )
    const { result } = renderHook(() => useAuth(), {
      wrapper: wrapperWith(createQueryClient()),
    })
    expect(result.current.status).toBe('loading')
    expect(result.current.user).toBeNull()
    expect(result.current.hasEverBeenAuthenticated).toBe(false)
  })

  it('reports authenticated after /me succeeds', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ sub: 'abc', email: 'e', name: null, roles: ['analyst'] }),
        { status: 200 },
      ),
    )
    const { result } = renderHook(() => useAuth(), {
      wrapper: wrapperWith(createQueryClient()),
    })
    await waitFor(() => expect(result.current.status).toBe('authenticated'))
    expect(result.current.user?.sub).toBe('abc')
    expect(result.current.hasEverBeenAuthenticated).toBe(true)
  })

  it('reports unauthenticated after /me 401 (via queryCache handler)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'nope' }), { status: 401 }),
    )
    const { result } = renderHook(() => useAuth(), {
      wrapper: wrapperWith(createQueryClient()),
    })
    await waitFor(() => expect(result.current.status).toBe('unauthenticated'))
    expect(result.current.user).toBeNull()
    // Never observed a successful auth — a 401 on first boot is a
    // config error, not a session expiry. Route gate branches on
    // this to avoid the login-redirect loop (D2.A.2).
    expect(result.current.hasEverBeenAuthenticated).toBe(false)
  })

  it('hasEverBeenAuthenticated flips to true ONLY on successful /me observation', async () => {
    // Start with success, then a 401 mid-session. The flag should
    // stay true after the flip because the session DID exist once.
    const fetchSpy = vi.spyOn(global, 'fetch')
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ sub: 'abc', email: 'e', name: null, roles: [] }),
        { status: 200 },
      ),
    )

    const client = createQueryClient()
    const { result, rerender } = renderHook(() => useAuth(), {
      wrapper: wrapperWith(client),
    })
    await waitFor(() => expect(result.current.status).toBe('authenticated'))
    expect(result.current.hasEverBeenAuthenticated).toBe(true)

    // Simulate an invalidation + 401 on the next /me call
    fetchSpy.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'expired' }), { status: 401 }),
    )
    await client.invalidateQueries({ queryKey: queryKeys.me() })
    rerender()

    await waitFor(() => expect(result.current.status).toBe('unauthenticated'))
    // Session expiry, NOT a first-boot config error — the flag
    // remains true so the route gate routes to /login normally
    // (not the diagnostic branch).
    expect(result.current.hasEverBeenAuthenticated).toBe(true)
  })
})
