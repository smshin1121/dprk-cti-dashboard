import { describe, expect, it } from 'vitest'

import { parseDetailId } from '../detailParams'

describe('parseDetailId', () => {
  it('parses positive integer strings', () => {
    expect(parseDetailId('42')).toBe(42)
    expect(parseDetailId('1')).toBe(1)
    expect(parseDetailId('999999')).toBe(999999)
  })

  it('returns null for undefined / empty', () => {
    expect(parseDetailId(undefined)).toBeNull()
    expect(parseDetailId('')).toBeNull()
  })

  it('returns null for non-numeric strings', () => {
    expect(parseDetailId('abc')).toBeNull()
    expect(parseDetailId('42abc42')).toBe(42) // parseInt truncates — integer prefix still valid
    expect(parseDetailId('abc42')).toBeNull()
  })

  it('returns null for zero or negative', () => {
    expect(parseDetailId('0')).toBeNull()
    expect(parseDetailId('-1')).toBeNull()
    expect(parseDetailId('-42')).toBeNull()
  })

  it('returns null for non-finite sentinels', () => {
    expect(parseDetailId('NaN')).toBeNull()
    expect(parseDetailId('Infinity')).toBeNull()
  })

  // Guard invariant: parseDetailId's output that is NOT null must
  // satisfy the detail hooks' `enabled: Number.isInteger(id) && id > 0`
  // condition. Tests in the hook files rely on this symmetry.
  it('non-null output always satisfies the hook enable condition', () => {
    for (const input of ['1', '42', '999']) {
      const id = parseDetailId(input)
      expect(id).not.toBeNull()
      expect(Number.isInteger(id!)).toBe(true)
      expect(id! > 0).toBe(true)
    }
  })
})
