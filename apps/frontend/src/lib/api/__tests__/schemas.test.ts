import { describe, expect, it } from 'vitest'

import { currentUserSchema } from '../schemas'

describe('currentUserSchema', () => {
  // Lifted verbatim from contracts/openapi/openapi.json (PR #11 Group
  // K D13 example for GET /auth/me). If the BE changes the example,
  // this test breaks first — desired, since it signals a contract
  // shift that the FE Zod must track.
  const beExample = {
    sub: 'abc-123',
    email: 'analyst@dprk.test',
    name: 'Jane Analyst',
    roles: ['analyst'],
  }

  it('parses the BE /auth/me 200 example verbatim', () => {
    const result = currentUserSchema.parse(beExample)
    expect(result).toEqual(beExample)
  })

  it('accepts null name (BE Optional[str] round-trip)', () => {
    const result = currentUserSchema.parse({ ...beExample, name: null })
    expect(result.name).toBeNull()
  })

  it('accepts missing name (BE Optional[str] with default None)', () => {
    const { name: _omitted, ...rest } = beExample
    const result = currentUserSchema.parse(rest)
    expect(result.name).toBeUndefined()
  })

  it('accepts empty roles array', () => {
    const result = currentUserSchema.parse({ ...beExample, roles: [] })
    expect(result.roles).toEqual([])
  })

  it('rejects missing sub', () => {
    const { sub: _omitted, ...rest } = beExample
    expect(() => currentUserSchema.parse(rest)).toThrow(/sub/i)
  })

  it('rejects missing email', () => {
    const { email: _omitted, ...rest } = beExample
    expect(() => currentUserSchema.parse(rest)).toThrow(/email/i)
  })

  it('rejects missing roles', () => {
    const { roles: _omitted, ...rest } = beExample
    expect(() => currentUserSchema.parse(rest)).toThrow(/roles/i)
  })

  it('rejects non-string role entries', () => {
    expect(() => currentUserSchema.parse({ ...beExample, roles: [1] })).toThrow()
  })
})
