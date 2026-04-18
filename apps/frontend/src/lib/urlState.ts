/**
 * URL-state encode / decode — plan D4 lock.
 *
 * Pure functions. No React, no router, no store imports. The sync
 * hook (`features/url-state/useFilterUrlSync`) owns the side-effect
 * wiring; this module is the serialization contract.
 *
 * STRICT KEY WHITELIST (plan D4 locked):
 *
 *   date_from   — ISO yyyy-mm-dd
 *   date_to     — ISO yyyy-mm-dd
 *   group_id    — repeatable, integer
 *   view        — opaque string (dashboard sub-view)
 *   tab         — opaque string (tab within a view)
 *
 * Nothing else surfaces in the URL — NOT TLP (plan D5 + D4 lock:
 * UI-only), NOT pagination cursor stack (ephemeral), NOT dialog-open
 * / hover / ⌘K-open (ephemeral), NOT auth tokens (cookie-scoped).
 * Extra keys passed to encode() are dropped at compile time (type
 * signature) AND at runtime (only the 5 known keys are written).
 * Extra keys present in a decoded URL are silently ignored.
 *
 * groupIds canonicalization:
 * Both encode AND decode sort ascending. Encode so [1,3] and [3,1]
 * produce identical URL strings (share React-Query cache scope —
 * carries the PR #12 Codex R1 P2 regression guard into the URL
 * layer). Decode so a hand-crafted URL like `?group_id=3&group_id=1`
 * hydrates to [1,3] (matches what the filter store emits back into
 * the URL on first sync, so the canonicalization write on mount is a
 * no-op rather than a visible "URL flapped" event).
 */

/** Shape the sync hook owns. Decoder returns this, encoder consumes
 *  the same shape. TLP / cursor / hover absent by construction. */
export interface UrlState {
  /** ISO yyyy-mm-dd, or null when no lower bound. */
  dateFrom: string | null
  /** ISO yyyy-mm-dd, or null when no upper bound. */
  dateTo: string | null
  /** Canonicalized (ascending sort) group ids. Always a fresh array. */
  groupIds: number[]
  /** Opaque dashboard sub-view key, null = default. */
  view: string | null
  /** Opaque tab-within-view key, null = default. */
  tab: string | null
}

export const EMPTY_URL_STATE: UrlState = {
  dateFrom: null,
  dateTo: null,
  groupIds: [],
  view: null,
  tab: null,
}

/** Single source of truth for the 5 keys this module owns. */
export const URL_STATE_KEYS = [
  'date_from',
  'date_to',
  'group_id',
  'view',
  'tab',
] as const

export function encodeUrlState(state: UrlState): URLSearchParams {
  const params = new URLSearchParams()
  if (state.dateFrom != null) params.append('date_from', state.dateFrom)
  if (state.dateTo != null) params.append('date_to', state.dateTo)
  if (state.groupIds.length > 0) {
    const sorted = [...state.groupIds].sort((a, b) => a - b)
    for (const id of sorted) params.append('group_id', String(id))
  }
  if (state.view != null && state.view !== '') {
    params.append('view', state.view)
  }
  if (state.tab != null && state.tab !== '') {
    params.append('tab', state.tab)
  }
  return params
}

export function decodeUrlState(params: URLSearchParams): UrlState {
  const rawGroupIds = params
    .getAll('group_id')
    .map((value) => Number.parseInt(value, 10))
    // Drop malformed entries — the router's AfterValidator rejects
    // group_id < 1 at the BE boundary too. A hand-crafted URL with
    // `group_id=abc` or `group_id=-1` hydrates to a clean [] + gets
    // emitted back out as no `group_id` param (canonicalization).
    .filter((n) => Number.isInteger(n) && n >= 1)

  const groupIds = [...new Set(rawGroupIds)].sort((a, b) => a - b)

  const view = params.get('view')
  const tab = params.get('tab')

  return {
    dateFrom: params.get('date_from'),
    dateTo: params.get('date_to'),
    groupIds,
    view: view != null && view !== '' ? view : null,
    tab: tab != null && tab !== '' ? tab : null,
  }
}

/**
 * Stable serialization for infinite-loop guard. Compares the encoded
 * form of two `UrlState` values — equal iff they hash to the same
 * URL search string.
 */
export function urlStateSearchString(state: UrlState): string {
  return encodeUrlState(state).toString()
}
