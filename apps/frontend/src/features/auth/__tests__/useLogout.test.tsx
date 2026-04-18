import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { queryKeys } from '../../../lib/queryKeys'
import { useLogout } from '../useLogout'

function wrapperWith(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useLogout', () => {
  it('POSTs /auth/logout and clears the entire query cache on success', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(new Response(null, { status: 204 }))

    const client = createQueryClient()
    client.setQueryData(queryKeys.me(), { sub: 'abc', email: 'e', roles: ['analyst'] })
    client.setQueryData(['actors', 'page-1'], { items: [{ id: 1 }] })
    client.setQueryData(['dashboard', 'summary'], { total_reports: 42 })

    const { result } = renderHook(() => useLogout(), { wrapper: wrapperWith(client) })

    await act(async () => {
      await result.current.mutateAsync()
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    // The nuclear-clear contract from useLogout.ts: post-logout, no
    // user-bound data remains. Stale filters, cursors, user menus,
    // list caches — all gone.
    expect(client.getQueryData(queryKeys.me())).toBeUndefined()
    expect(client.getQueryData(['actors', 'page-1'])).toBeUndefined()
    expect(client.getQueryData(['dashboard', 'summary'])).toBeUndefined()
    expect(client.getQueryCache().getAll()).toHaveLength(0)
  })

  it('surfaces backend failure as mutation.isError without clearing cache', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'server-error' }), { status: 500 }),
    )
    const client = createQueryClient()
    const seeded = { sub: 'abc', email: 'e', roles: [] }
    client.setQueryData(queryKeys.me(), seeded)

    const { result } = renderHook(() => useLogout(), { wrapper: wrapperWith(client) })

    await act(async () => {
      await result.current.mutateAsync().catch(() => {})
    })

    await waitFor(() => expect(result.current.isError).toBe(true))
    // Failed logout must NOT clear — else an intermittent 5xx would
    // locally sign the user out while the server session is still
    // valid. User retries logout; server eventually succeeds; then
    // we clear.
    expect(client.getQueryData(queryKeys.me())).toEqual(seeded)
  })
})
