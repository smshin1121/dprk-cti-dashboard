import { describe, expect, it } from 'vitest'

import { URL_STATE_KEYS } from '../../../lib/urlState'

/**
 * URL-state invariance — plan D18 carry for PR #17 Phase 3 slice 3.
 *
 * The /search slice adds a `q` input to the command palette but does
 * NOT surface it in the URL — q is ephemeral palette state (same
 * tier as dialog-open / hover). The 5-key whitelist locked in PR #13
 * stays exactly as-is. This test mirrors the PR #15 Group E
 * `scope-lock.test.ts::URL_STATE_KEYS invariance` suite — identical
 * structure so a future reviewer scanning the test tree sees the
 * same shape applied to this slice.
 *
 * If a future PR legitimately needs `q` or `search` in the URL
 * (permalink, shareable deep-link), that's a scope change — this
 * test's expectation must be updated in the SAME PR that widens
 * the whitelist, NOT silently relaxed.
 */

describe('URL_STATE_KEYS invariance — PR #17 does not add URL state', () => {
  it('URL_STATE_KEYS remains the PR #13 locked 5-tuple', () => {
    expect([...URL_STATE_KEYS]).toEqual([
      'date_from',
      'date_to',
      'group_id',
      'view',
      'tab',
    ])
  })

  it('URL_STATE_KEYS does NOT include a search / q / query marker', () => {
    // Plan D18 locks q OUT of the URL surface. Search input lives in
    // palette-local state, not router state — so refresh / share /
    // deep-link semantics do not surface a mid-typed query.
    const joined = [...URL_STATE_KEYS].join(' ').toLowerCase()
    expect(joined).not.toContain('search')
    expect(joined).not.toContain('query')
    // The exact key 'q' would match inside 'date_from' etc. via
    // substring — scan each key separately instead.
    for (const k of URL_STATE_KEYS) {
      expect(k).not.toBe('q')
      expect(k).not.toMatch(/search|query|q_text|q_string/i)
    }
  })

  it('URL_STATE_KEYS does NOT include an fts / rank / hit marker', () => {
    // Guard against a different failure mode: a future edit adding
    // fts-specific keys (fts_q, rank_by, hit_id) to the URL. None of
    // these belong in the router — all are ephemeral render state.
    for (const k of URL_STATE_KEYS) {
      expect(k).not.toMatch(/fts|rank|hit/i)
    }
  })
})
