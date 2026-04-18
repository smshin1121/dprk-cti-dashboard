import { beforeEach, describe, expect, it } from 'vitest'

import { useAuthStore } from '../auth'

describe('useAuthStore', () => {
  beforeEach(() => {
    // zustand stores persist module state across tests; reset the
    // single field this store owns before each case.
    useAuthStore.setState({ postLoginRedirect: null })
  })

  it('starts with postLoginRedirect: null', () => {
    expect(useAuthStore.getState().postLoginRedirect).toBeNull()
  })

  it('setPostLoginRedirect records a path', () => {
    useAuthStore.getState().setPostLoginRedirect('/reports')
    expect(useAuthStore.getState().postLoginRedirect).toBe('/reports')
  })

  it('clearPostLoginRedirect resets to null', () => {
    useAuthStore.getState().setPostLoginRedirect('/dashboard')
    useAuthStore.getState().clearPostLoginRedirect()
    expect(useAuthStore.getState().postLoginRedirect).toBeNull()
  })

  // D10 lock: prevent future drift into "user/roles mirror" shape.
  // If someone adds `user` / `roles` / `isAuthenticated` to the
  // store, this test flips red so reviewer catches it before merge.
  it('exposes only the documented auth-UI fields — D10 source-of-truth lock', () => {
    const state = useAuthStore.getState()
    const keys = Object.keys(state).sort()
    expect(keys).toEqual([
      'clearPostLoginRedirect',
      'postLoginRedirect',
      'setPostLoginRedirect',
    ])
  })
})
