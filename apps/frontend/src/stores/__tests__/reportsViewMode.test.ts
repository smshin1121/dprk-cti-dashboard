import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  REPORTS_VIEW_MODES,
  REPORTS_VIEW_MODE_STORAGE_KEY,
  isValidReportsViewMode,
  useReportsViewModeStore,
} from '../reportsViewMode'

function reset(): void {
  window.localStorage.clear()
  useReportsViewModeStore.setState({ mode: 'list' })
}

describe('isValidReportsViewMode', () => {
  it('accepts the two view modes', () => {
    for (const mode of REPORTS_VIEW_MODES) {
      expect(isValidReportsViewMode(mode)).toBe(true)
    }
  })

  it('rejects invalid + stale values', () => {
    expect(isValidReportsViewMode('grid')).toBe(false)
    expect(isValidReportsViewMode('')).toBe(false)
    expect(isValidReportsViewMode(null)).toBe(false)
    expect(isValidReportsViewMode(undefined)).toBe(false)
  })
})

describe('useReportsViewModeStore', () => {
  beforeEach(reset)
  afterEach(reset)

  it('defaults to list mode when storage is empty', () => {
    expect(useReportsViewModeStore.getState().mode).toBe('list')
  })

  it.each(['list', 'timeline'] as const)(
    'setMode writes %s to localStorage and store',
    (mode) => {
      useReportsViewModeStore.getState().setMode(mode)
      expect(window.localStorage.getItem(REPORTS_VIEW_MODE_STORAGE_KEY)).toBe(
        mode,
      )
      expect(useReportsViewModeStore.getState().mode).toBe(mode)
    },
  )

  it('toggleMode flips list ↔ timeline both directions', () => {
    expect(useReportsViewModeStore.getState().mode).toBe('list')
    useReportsViewModeStore.getState().toggleMode()
    expect(useReportsViewModeStore.getState().mode).toBe('timeline')
    expect(window.localStorage.getItem(REPORTS_VIEW_MODE_STORAGE_KEY)).toBe(
      'timeline',
    )
    useReportsViewModeStore.getState().toggleMode()
    expect(useReportsViewModeStore.getState().mode).toBe('list')
    expect(window.localStorage.getItem(REPORTS_VIEW_MODE_STORAGE_KEY)).toBe(
      'list',
    )
  })

  it('ignores invalid setMode input', () => {
    useReportsViewModeStore.getState().setMode('timeline')
    useReportsViewModeStore.getState().setMode('not-a-mode' as never)
    expect(useReportsViewModeStore.getState().mode).toBe('timeline')
  })
})
