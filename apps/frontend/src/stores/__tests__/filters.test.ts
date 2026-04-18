import { beforeEach, describe, expect, it } from 'vitest'

import {
  TLP_LEVELS,
  type TlpLevel,
  useFilterStore,
} from '../filters'

const EMPTY_STATE = {
  dateFrom: null,
  dateTo: null,
  groupIds: [] as number[],
  tlpLevels: [] as TlpLevel[],
}

describe('useFilterStore', () => {
  beforeEach(() => {
    useFilterStore.setState(EMPTY_STATE)
  })

  it('starts with all filter dimensions empty', () => {
    const state = useFilterStore.getState()
    expect(state.dateFrom).toBeNull()
    expect(state.dateTo).toBeNull()
    expect(state.groupIds).toEqual([])
    expect(state.tlpLevels).toEqual([])
  })

  it('setDateRange records both ends as ISO strings', () => {
    useFilterStore.getState().setDateRange('2026-01-01', '2026-04-18')
    const state = useFilterStore.getState()
    expect(state.dateFrom).toBe('2026-01-01')
    expect(state.dateTo).toBe('2026-04-18')
  })

  it('setDateRange accepts partial ranges (one end null)', () => {
    useFilterStore.getState().setDateRange('2026-01-01', null)
    expect(useFilterStore.getState().dateTo).toBeNull()
  })

  it('toggleGroupId adds when absent, removes when present', () => {
    useFilterStore.getState().toggleGroupId(3)
    expect(useFilterStore.getState().groupIds).toEqual([3])
    useFilterStore.getState().toggleGroupId(5)
    expect(useFilterStore.getState().groupIds).toEqual([3, 5])
    useFilterStore.getState().toggleGroupId(3)
    expect(useFilterStore.getState().groupIds).toEqual([5])
  })

  it('toggleGroupId is immutable — produces new array reference', () => {
    const before = useFilterStore.getState().groupIds
    useFilterStore.getState().toggleGroupId(1)
    const after = useFilterStore.getState().groupIds
    expect(after).not.toBe(before)
  })

  it('toggleTlpLevel adds when absent, removes when present', () => {
    useFilterStore.getState().toggleTlpLevel('AMBER')
    expect(useFilterStore.getState().tlpLevels).toEqual(['AMBER'])
    useFilterStore.getState().toggleTlpLevel('GREEN')
    expect(useFilterStore.getState().tlpLevels).toEqual(['AMBER', 'GREEN'])
    useFilterStore.getState().toggleTlpLevel('AMBER')
    expect(useFilterStore.getState().tlpLevels).toEqual(['GREEN'])
  })

  it('clear() resets every field to its empty value', () => {
    useFilterStore.setState({
      dateFrom: '2026-01-01',
      dateTo: '2026-04-18',
      groupIds: [1, 2, 3],
      tlpLevels: ['WHITE', 'AMBER'],
    })
    useFilterStore.getState().clear()
    const state = useFilterStore.getState()
    expect(state.dateFrom).toBeNull()
    expect(state.dateTo).toBeNull()
    expect(state.groupIds).toEqual([])
    expect(state.tlpLevels).toEqual([])
  })

  it('TLP_LEVELS exposes exactly the three FE-displayable values', () => {
    // RED is intentionally excluded — design doc §9.4 reserves RED for
    // workflow approval gating, not dashboard display. Adding RED here
    // would silently expose RED-classified incidents in the analyst
    // view; reviewer should bounce that PR.
    expect([...TLP_LEVELS]).toEqual(['WHITE', 'GREEN', 'AMBER'])
  })

  // D10 source-of-truth lock + D5 TLP-UI-only lock combined: pin the
  // store's surface so future fields can't sneak in without a test
  // change. New filter dimensions belong here, not in a parallel store.
  it('exposes only the documented filter fields + actions', () => {
    const state = useFilterStore.getState()
    const keys = Object.keys(state).sort()
    expect(keys).toEqual([
      'clear',
      'dateFrom',
      'dateTo',
      'groupIds',
      'setDateRange',
      'tlpLevels',
      'toggleGroupId',
      'toggleTlpLevel',
    ])
  })
})
