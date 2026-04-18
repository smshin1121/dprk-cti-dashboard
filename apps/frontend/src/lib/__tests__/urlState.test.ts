import { describe, expect, it } from 'vitest'

import {
  decodeUrlState,
  encodeUrlState,
  EMPTY_URL_STATE,
  urlStateSearchString,
  URL_STATE_KEYS,
  type UrlState,
} from '../urlState'

function params(input: Record<string, string | string[]>): URLSearchParams {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(input)) {
    if (Array.isArray(v)) {
      for (const entry of v) p.append(k, entry)
    } else {
      p.append(k, v)
    }
  }
  return p
}

describe('URL_STATE_KEYS (whitelist)', () => {
  it('locks the 5-key whitelist at the module level', () => {
    // Plan D4 lock: NOT TLP, NOT pagination cursor, NOT dialog
    // state, NOT hover. If this list ever grows, review the D4
    // lock before accepting the addition.
    expect(URL_STATE_KEYS).toEqual([
      'date_from',
      'date_to',
      'group_id',
      'view',
      'tab',
    ])
  })
})

describe('encodeUrlState', () => {
  it('returns empty params for EMPTY_URL_STATE', () => {
    expect(encodeUrlState(EMPTY_URL_STATE).toString()).toBe('')
  })

  it('emits date_from / date_to when set', () => {
    const p = encodeUrlState({
      ...EMPTY_URL_STATE,
      dateFrom: '2026-01-01',
      dateTo: '2026-04-18',
    })
    expect(p.get('date_from')).toBe('2026-01-01')
    expect(p.get('date_to')).toBe('2026-04-18')
  })

  it('emits group_id repeated, sorted ascending (canonicalization)', () => {
    const p = encodeUrlState({
      ...EMPTY_URL_STATE,
      groupIds: [3, 1, 5],
    })
    expect(p.getAll('group_id')).toEqual(['1', '3', '5'])
  })

  it('identical group sets in different toggle orders produce identical URLs', () => {
    // Same invariant as PR #12 Codex R1 P2 — carried into the URL
    // layer. Without this, swapping group toggle order would change
    // the URL string and cause a back-button entry.
    const a = urlStateSearchString({
      ...EMPTY_URL_STATE,
      groupIds: [1, 3],
    })
    const b = urlStateSearchString({
      ...EMPTY_URL_STATE,
      groupIds: [3, 1],
    })
    expect(a).toBe(b)
  })

  it('emits view / tab when set', () => {
    const p = encodeUrlState({
      ...EMPTY_URL_STATE,
      view: 'attack',
      tab: 'overview',
    })
    expect(p.get('view')).toBe('attack')
    expect(p.get('tab')).toBe('overview')
  })

  it('omits empty-string view / tab (null-equivalent)', () => {
    const p = encodeUrlState({
      ...EMPTY_URL_STATE,
      view: '',
      tab: '',
    })
    expect(p.has('view')).toBe(false)
    expect(p.has('tab')).toBe(false)
  })

  it('does NOT emit any non-whitelist key even if snuck in', () => {
    const p = encodeUrlState({
      ...EMPTY_URL_STATE,
      // @ts-expect-error — intentionally smuggle TLP-shaped data
      tlp: 'AMBER',
      // @ts-expect-error — cursor should never reach the URL
      cursor: 'MjAyNi0wMy0xNXw0Mg',
      // @ts-expect-error — hover is ephemeral UI state
      hoveredActorId: 42,
      groupIds: [1],
    })
    for (const key of p.keys()) {
      expect(URL_STATE_KEYS as readonly string[]).toContain(key)
    }
  })
})

describe('decodeUrlState', () => {
  it('returns EMPTY_URL_STATE shape for empty params', () => {
    expect(decodeUrlState(new URLSearchParams())).toEqual(EMPTY_URL_STATE)
  })

  it('decodes date_from / date_to as strings', () => {
    const state = decodeUrlState(
      params({ date_from: '2026-01-01', date_to: '2026-04-18' }),
    )
    expect(state.dateFrom).toBe('2026-01-01')
    expect(state.dateTo).toBe('2026-04-18')
  })

  it('decodes repeatable group_id into a sorted numeric array', () => {
    const state = decodeUrlState(
      params({ group_id: ['3', '1', '5'] }),
    )
    expect(state.groupIds).toEqual([1, 3, 5])
  })

  it('deduplicates group_id entries', () => {
    const state = decodeUrlState(params({ group_id: ['3', '1', '3'] }))
    expect(state.groupIds).toEqual([1, 3])
  })

  it('drops malformed group_id entries (non-integer, < 1)', () => {
    const state = decodeUrlState(
      params({ group_id: ['abc', '-1', '0', '2', '3.5'] }),
    )
    // 'abc' NaN → drop; -1 < 1 → drop; 0 < 1 → drop; 3.5 → parseInt
    // yields 3 which is valid. So result = [2, 3].
    expect(state.groupIds).toEqual([2, 3])
  })

  it('decodes view / tab as strings or null', () => {
    const withBoth = decodeUrlState(params({ view: 'attack', tab: 'overview' }))
    expect(withBoth.view).toBe('attack')
    expect(withBoth.tab).toBe('overview')

    const withoutAny = decodeUrlState(new URLSearchParams())
    expect(withoutAny.view).toBeNull()
    expect(withoutAny.tab).toBeNull()
  })

  it('treats empty-string view / tab as null', () => {
    const state = decodeUrlState(params({ view: '', tab: '' }))
    expect(state.view).toBeNull()
    expect(state.tab).toBeNull()
  })

  it('IGNORES every non-whitelist key on decode', () => {
    // A hand-crafted URL (or older bookmarked URL from a pre-plan-
    // lock era) carrying tlp/cursor/hover/⌘K-open must NOT surface
    // in the decoded state shape. The UrlState interface has no
    // field for any of those.
    const state = decodeUrlState(
      params({
        date_from: '2026-01-01',
        tlp: 'AMBER',
        cursor: 'MjAyNi0wMy0xNXw0Mg',
        hoveredActorId: '42',
        dialogOpen: 'true',
        cmdkOpen: 'true',
      }),
    )
    const keys = Object.keys(state)
    expect(keys).toEqual(['dateFrom', 'dateTo', 'groupIds', 'view', 'tab'])
    expect(state.dateFrom).toBe('2026-01-01')
  })
})

describe('encode/decode round-trip', () => {
  it.each<UrlState>([
    EMPTY_URL_STATE,
    {
      dateFrom: '2026-01-01',
      dateTo: '2026-04-18',
      groupIds: [1, 3],
      view: 'attack',
      tab: 'overview',
    },
    {
      dateFrom: '2026-03-15',
      dateTo: null,
      groupIds: [7],
      view: null,
      tab: null,
    },
  ])('state %# round-trips losslessly', (state) => {
    const encoded = encodeUrlState(state)
    const decoded = decodeUrlState(encoded)
    expect(decoded).toEqual(state)
  })

  it('decode canonicalizes URLs that already match after encode', () => {
    // Given a non-canonical URL (group_id out of order), decode
    // produces canonical state, re-encode yields canonical URL,
    // so the sync hook's "URL matches current state" short-circuit
    // stabilizes after one sync cycle.
    const nonCanonical = params({ group_id: ['5', '1', '3'] })
    const decoded = decodeUrlState(nonCanonical)
    const reEncoded = encodeUrlState(decoded).toString()
    expect(reEncoded).toBe('group_id=1&group_id=3&group_id=5')
  })
})
