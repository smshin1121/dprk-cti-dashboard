import { describe, expect, it } from 'vitest'

import { currentUserSchema, dashboardSummarySchema } from '../schemas'

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

describe('dashboardSummarySchema', () => {
  // Lifted verbatim from contracts/openapi/openapi.json (PR #11 Group
  // K D13 example — components.schemas.DashboardSummary.examples[0]).
  // If the BE example changes, this test breaks first — the exact
  // signal D7 relies on until OpenAPI→Zod codegen lands.
  const beHappyExample = {
    total_reports: 1204,
    total_incidents: 154,
    total_actors: 12,
    reports_by_year: [
      { year: 2022, count: 201 },
      { year: 2023, count: 287 },
      { year: 2024, count: 318 },
    ],
    incidents_by_motivation: [
      { motivation: 'financial', count: 81 },
      { motivation: 'espionage', count: 52 },
      { motivation: 'disruption', count: 21 },
    ],
    top_groups: [
      { group_id: 3, name: 'Lazarus Group', report_count: 412 },
      { group_id: 5, name: 'Kimsuky', report_count: 287 },
    ],
  }

  const beEmptyExample = {
    total_reports: 0,
    total_incidents: 0,
    total_actors: 0,
    reports_by_year: [],
    incidents_by_motivation: [],
    top_groups: [],
  }

  it('parses the BE happy example verbatim', () => {
    const parsed = dashboardSummarySchema.parse(beHappyExample)
    expect(parsed).toEqual(beHappyExample)
  })

  it('parses the BE empty-DB example verbatim', () => {
    expect(dashboardSummarySchema.parse(beEmptyExample)).toEqual(beEmptyExample)
  })

  it('rejects negative scalar totals (BE `ge=0`)', () => {
    expect(() =>
      dashboardSummarySchema.parse({ ...beEmptyExample, total_reports: -1 }),
    ).toThrow()
  })

  it('rejects missing top_groups entry fields', () => {
    expect(() =>
      dashboardSummarySchema.parse({
        ...beEmptyExample,
        top_groups: [{ group_id: 3, name: 'x' }],
      }),
    ).toThrow(/report_count/i)
  })

  it('rejects out-of-range year', () => {
    expect(() =>
      dashboardSummarySchema.parse({
        ...beEmptyExample,
        reports_by_year: [{ year: 1800, count: 1 }],
      }),
    ).toThrow()
  })
})
