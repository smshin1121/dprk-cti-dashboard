import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useMe } from '../useMe'

function wrapperWith(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useMe', () => {
  it('resolves CurrentUser on 200', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          sub: 'abc',
          email: 'a@test',
          name: null,
          roles: ['analyst'],
        }),
        { status: 200 },
      ),
    )

    const { result } = renderHook(() => useMe(), {
      wrapper: wrapperWith(createQueryClient()),
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.sub).toBe('abc')
    expect(result.current.data?.roles).toEqual(['analyst'])
  })

  it('surfaces ApiError 401 as null cached data via queryCache handler', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'nope' }), { status: 401 }),
    )
    const client = createQueryClient()
    const { result } = renderHook(() => useMe(), { wrapper: wrapperWith(client) })

    // queryCache onError intercepts the 401 and sets ['me'] to null.
    // This explicitly LEAVES the query in a success state (with
    // data=null) rather than isError=true — see queryClient.ts module
    // docstring: we flip identity to "unauthenticated" in one render
    // pass without triggering React Query's default retry/error
    // backoff path.
    await waitFor(() => expect(client.getQueryData(['me'])).toBeNull())
    expect(result.current.data).toBeNull()
  })
})
