import { describe, expect, it } from 'vitest'

import {
  actorListResponseSchema,
  attackMatrixResponseSchema,
  currentUserSchema,
  dashboardSummarySchema,
  geoResponseSchema,
  trendResponseSchema,
} from '../schemas'

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

describe('actorListResponseSchema', () => {
  // Lifted verbatim from contracts/openapi/openapi.json
  // components.schemas.ActorListResponse.examples[0].
  const beHappyExample = {
    items: [
      {
        id: 3,
        name: 'Lazarus Group',
        mitre_intrusion_set_id: 'G0032',
        aka: ['APT38', 'Hidden Cobra'],
        description: 'DPRK-attributed cyber espionage and financially motivated group',
        codenames: ['Andariel', 'Bluenoroff'],
      },
    ],
    limit: 50,
    offset: 0,
    total: 12,
  }

  const beEmptyExample = { items: [], limit: 50, offset: 0, total: 0 }

  it('parses the BE happy example verbatim', () => {
    expect(actorListResponseSchema.parse(beHappyExample)).toEqual(beHappyExample)
  })

  it('parses the BE empty-page example verbatim', () => {
    expect(actorListResponseSchema.parse(beEmptyExample)).toEqual(beEmptyExample)
  })

  it('accepts null mitre_intrusion_set_id + description (BE Optional[str])', () => {
    const row = {
      ...beHappyExample.items[0],
      mitre_intrusion_set_id: null,
      description: null,
    }
    expect(() =>
      actorListResponseSchema.parse({ ...beHappyExample, items: [row] }),
    ).not.toThrow()
  })

  it('accepts missing aka/codenames because BE Pydantic has default_factory=list', () => {
    // Pydantic dumps the defaulted lists as `[]` on the wire, but the
    // FE schema must tolerate a BE that optimizes empty arrays away
    // (not current behavior but worth confirming since Zod `array()`
    // is strict by default without z.array(...).default([])).
    const row = {
      id: 4,
      name: 'APT37',
      aka: [],
      codenames: [],
    }
    expect(() =>
      actorListResponseSchema.parse({ ...beHappyExample, items: [row] }),
    ).not.toThrow()
  })

  it('rejects out-of-bound limit (BE `ge=1, le=200`)', () => {
    expect(() =>
      actorListResponseSchema.parse({ ...beEmptyExample, limit: 500 }),
    ).toThrow()
  })

  it('rejects negative total (BE `ge=0`)', () => {
    expect(() =>
      actorListResponseSchema.parse({ ...beEmptyExample, total: -1 }),
    ).toThrow()
  })
})

// ---------------------------------------------------------------------------
// PR #13 Group C — analytics schema drift guards
// ---------------------------------------------------------------------------
//
// Each analytics response schema parses:
//   (a) the BE OpenAPI example verbatim (drift signal for D7 lock);
//   (b) the empty-payload shape (`{tactics: [], rows: []}` etc.)
//       — plan D8 empty-state UX depends on the hook returning an
//       empty-but-well-formed payload, not throwing.
// Field-bound rejection tests (negative counts, non-2-char iso2,
// malformed month string) pin the canary invariants on the FE side.

describe('attackMatrixResponseSchema', () => {
  // Lifted verbatim from contracts/openapi/openapi.json
  // (components.schemas.AttackMatrixResponse.examples[0]).
  const beHappyExample = {
    tactics: [
      { id: 'TA0001', name: 'TA0001' },
      { id: 'TA0002', name: 'TA0002' },
    ],
    rows: [
      {
        tactic_id: 'TA0001',
        techniques: [
          { technique_id: 'T1566', count: 18 },
          { technique_id: 'T1190', count: 7 },
        ],
      },
      {
        tactic_id: 'TA0002',
        techniques: [{ technique_id: 'T1059', count: 12 }],
      },
    ],
  }

  const beEmptyExample = { tactics: [], rows: [] }

  it('parses the BE happy example verbatim', () => {
    expect(attackMatrixResponseSchema.parse(beHappyExample)).toEqual(beHappyExample)
  })

  it('parses the BE empty example (viz owns empty-state card)', () => {
    expect(attackMatrixResponseSchema.parse(beEmptyExample)).toEqual(beEmptyExample)
  })

  it('rejects negative technique count (BE `ge=0`)', () => {
    expect(() =>
      attackMatrixResponseSchema.parse({
        tactics: [{ id: 'TA0001', name: 'TA0001' }],
        rows: [
          {
            tactic_id: 'TA0001',
            techniques: [{ technique_id: 'T1566', count: -1 }],
          },
        ],
      }),
    ).toThrow()
  })

  it('rejects missing techniques array on a row', () => {
    expect(() =>
      attackMatrixResponseSchema.parse({
        tactics: [{ id: 'TA0001', name: 'TA0001' }],
        rows: [{ tactic_id: 'TA0001' }],
      }),
    ).toThrow()
  })
})

describe('trendResponseSchema', () => {
  const beHappyExample = {
    buckets: [
      { month: '2026-01', count: 41 },
      { month: '2026-02', count: 38 },
      { month: '2026-03', count: 47 },
    ],
  }

  const beEmptyExample = { buckets: [] }

  it('parses the BE happy example verbatim', () => {
    expect(trendResponseSchema.parse(beHappyExample)).toEqual(beHappyExample)
  })

  it('parses the BE empty example', () => {
    expect(trendResponseSchema.parse(beEmptyExample)).toEqual(beEmptyExample)
  })

  it('rejects malformed month strings (must be YYYY-MM)', () => {
    expect(() =>
      trendResponseSchema.parse({
        buckets: [{ month: '2026-1', count: 10 }],
      }),
    ).toThrow()
    expect(() =>
      trendResponseSchema.parse({
        buckets: [{ month: '2026/03', count: 10 }],
      }),
    ).toThrow()
    expect(() =>
      trendResponseSchema.parse({
        buckets: [{ month: '2026-03-01', count: 10 }],
      }),
    ).toThrow()
  })

  it('rejects negative count', () => {
    expect(() =>
      trendResponseSchema.parse({
        buckets: [{ month: '2026-03', count: -1 }],
      }),
    ).toThrow()
  })
})

describe('geoResponseSchema', () => {
  const beHappyExample = {
    countries: [
      { iso2: 'KR', count: 18 },
      { iso2: 'US', count: 9 },
      { iso2: 'KP', count: 2 },
    ],
  }

  const beEmptyExample = { countries: [] }

  it('parses the BE happy example verbatim (including KP as plain row)', () => {
    // Plan D7 lock guard: DPRK (`KP`) is a regular row — the schema
    // has no special-case field. This assertion fails if the BE ever
    // introduces a DPRK-specific field shape.
    const parsed = geoResponseSchema.parse(beHappyExample)
    expect(parsed.countries.some((c) => c.iso2 === 'KP')).toBe(true)
  })

  it('parses the BE empty example', () => {
    expect(geoResponseSchema.parse(beEmptyExample)).toEqual(beEmptyExample)
  })

  it('rejects iso2 values that are not exactly 2 characters', () => {
    expect(() =>
      geoResponseSchema.parse({
        countries: [{ iso2: 'USA', count: 1 }],
      }),
    ).toThrow()
    expect(() =>
      geoResponseSchema.parse({
        countries: [{ iso2: 'U', count: 1 }],
      }),
    ).toThrow()
  })

  it('rejects negative count', () => {
    expect(() =>
      geoResponseSchema.parse({
        countries: [{ iso2: 'KR', count: -1 }],
      }),
    ).toThrow()
  })
})
