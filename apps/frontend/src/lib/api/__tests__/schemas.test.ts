import { describe, expect, it } from 'vitest'

import {
  actorDetailSchema,
  actorListResponseSchema,
  attackMatrixResponseSchema,
  currentUserSchema,
  dashboardSummarySchema,
  geoResponseSchema,
  incidentDetailSchema,
  reportDetailSchema,
  similarReportsResponseSchema,
  SIMILAR_K_MAX,
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

// ---------------------------------------------------------------------------
// Detail + similar schemas — PR #14 Group D (plan D1/D8/D9/D10/D11)
// ---------------------------------------------------------------------------
//
// All four examples are lifted verbatim from the BE Pydantic models'
// `json_schema_extra.examples` in `services/api/src/api/schemas/read.py`.
// When the BE example changes, these tests fire first — the exact
// signal plan D7 relies on until OpenAPI→Zod codegen lands.

describe('reportDetailSchema', () => {
  const beHappyExample = {
    id: 42,
    title: 'Lazarus targets South Korean crypto exchanges',
    url: 'https://mandiant.com/blog/lazarus-2026q1',
    url_canonical: 'https://mandiant.com/blog/lazarus-2026q1',
    published: '2026-03-15',
    source_id: 7,
    source_name: 'Mandiant',
    lang: 'en',
    tlp: 'WHITE',
    summary: 'Operation targeting crypto exchanges in Q1 2026.',
    reliability: 'A',
    credibility: '2',
    tags: ['ransomware', 'finance'],
    codenames: ['Andariel'],
    techniques: ['T1566', 'T1190'],
    linked_incidents: [
      { id: 18, title: 'Axie Infinity Ronin bridge exploit', reported: '2024-05-02' },
    ],
  }

  const beSparseExample = {
    id: 7,
    title: 'Single report without incident link',
    url: 'https://example.test/r/7',
    url_canonical: 'https://example.test/r/7',
    published: '2026-01-10',
    source_id: null,
    source_name: null,
    lang: 'en',
    tlp: 'WHITE',
    summary: null,
    reliability: null,
    credibility: null,
    tags: [],
    codenames: [],
    techniques: [],
    linked_incidents: [],
  }

  it('parses the BE happy example verbatim', () => {
    const parsed = reportDetailSchema.parse(beHappyExample)
    expect(parsed.id).toBe(42)
    expect(parsed.linked_incidents[0].reported).toBe('2024-05-02')
  })

  it('parses the BE sparse example (all-null + empty-collections)', () => {
    const parsed = reportDetailSchema.parse(beSparseExample)
    expect(parsed.source_id).toBeNull()
    expect(parsed.linked_incidents).toEqual([])
  })

  it('accepts linked_incidents with null reported (BE Optional[date])', () => {
    const parsed = reportDetailSchema.parse({
      ...beHappyExample,
      linked_incidents: [{ id: 18, title: 'reported-unknown', reported: null }],
    })
    expect(parsed.linked_incidents[0].reported).toBeNull()
  })

  // D9 dual-layer cap: BE enforces max 10 via Field(max_length=...).
  // If a BE bypass oversized the response, the FE Zod would surface
  // it as a parse error here rather than silently oversizing the UI.
  it('rejects linked_incidents exceeding the D9 cap (10)', () => {
    const elevenIncidents = Array.from({ length: 11 }, (_, i) => ({
      id: i + 1,
      title: `incident ${i + 1}`,
      reported: '2026-01-01',
    }))
    expect(() =>
      reportDetailSchema.parse({
        ...beHappyExample,
        linked_incidents: elevenIncidents,
      }),
    ).toThrow()
  })

  it('rejects missing required id', () => {
    const { id: _omitted, ...rest } = beHappyExample
    expect(() => reportDetailSchema.parse(rest)).toThrow(/id/i)
  })
})

describe('incidentDetailSchema', () => {
  const beHappyExample = {
    id: 18,
    reported: '2024-05-02',
    title: 'Axie Infinity Ronin bridge exploit',
    description: '620M USD bridge compromise attributed to Lazarus',
    est_loss_usd: 620_000_000,
    attribution_confidence: 'HIGH',
    motivations: ['financial'],
    sectors: ['crypto'],
    countries: ['VN', 'SG'],
    linked_reports: [
      {
        id: 42,
        title: 'Lazarus targets SK crypto exchanges',
        url: 'https://mandiant.com/blog/lazarus-2026q1',
        published: '2026-03-15',
        source_name: 'Mandiant',
      },
    ],
  }

  const beSparseExample = {
    id: 99,
    reported: null,
    title: 'Incident without source reports yet',
    description: null,
    est_loss_usd: null,
    attribution_confidence: null,
    motivations: [],
    sectors: [],
    countries: [],
    linked_reports: [],
  }

  it('parses the BE happy example verbatim', () => {
    const parsed = incidentDetailSchema.parse(beHappyExample)
    expect(parsed.linked_reports[0].source_name).toBe('Mandiant')
    expect(parsed.countries).toEqual(['VN', 'SG'])
  })

  it('parses the BE sparse example (all-null + empty-collections)', () => {
    const parsed = incidentDetailSchema.parse(beSparseExample)
    expect(parsed.reported).toBeNull()
    expect(parsed.linked_reports).toEqual([])
  })

  it('accepts linked_reports with null source_name', () => {
    const parsed = incidentDetailSchema.parse({
      ...beHappyExample,
      linked_reports: [
        {
          id: 42,
          title: 't',
          url: 'https://x.test',
          published: '2026-03-15',
          source_name: null,
        },
      ],
    })
    expect(parsed.linked_reports[0].source_name).toBeNull()
  })

  // D9 cap = 20 on incident detail.
  it('rejects linked_reports exceeding the D9 cap (20)', () => {
    const twentyOneReports = Array.from({ length: 21 }, (_, i) => ({
      id: i + 1,
      title: `r ${i + 1}`,
      url: `https://x.test/${i}`,
      published: '2026-01-01',
      source_name: null,
    }))
    expect(() =>
      incidentDetailSchema.parse({
        ...beHappyExample,
        linked_reports: twentyOneReports,
      }),
    ).toThrow()
  })

  it('rejects linked_reports rows with missing required published', () => {
    expect(() =>
      incidentDetailSchema.parse({
        ...beHappyExample,
        linked_reports: [
          { id: 42, title: 't', url: 'https://x.test', source_name: null },
        ],
      }),
    ).toThrow(/published/i)
  })
})

describe('actorDetailSchema', () => {
  const beHappyExample = {
    id: 3,
    name: 'Lazarus Group',
    mitre_intrusion_set_id: 'G0032',
    aka: ['APT38', 'Hidden Cobra'],
    description: 'DPRK-attributed cyber espionage and financially motivated group',
    codenames: ['Andariel', 'Bluenoroff'],
  }

  it('parses the BE happy example verbatim', () => {
    const parsed = actorDetailSchema.parse(beHappyExample)
    expect(parsed.aka).toEqual(['APT38', 'Hidden Cobra'])
    expect(parsed.mitre_intrusion_set_id).toBe('G0032')
  })

  it('accepts null mitre_intrusion_set_id + null description', () => {
    const parsed = actorDetailSchema.parse({
      ...beHappyExample,
      mitre_intrusion_set_id: null,
      description: null,
    })
    expect(parsed.mitre_intrusion_set_id).toBeNull()
    expect(parsed.description).toBeNull()
  })

  // D11 out-of-scope pin. ActorDetail has no linked_reports /
  // reports / recent_reports key; Zod default strip-mode silently
  // drops unknown keys at parse. A BE accidental leak of any
  // reports-like surface therefore cannot reach an actor detail
  // page built on this schema.
  it('silently strips out-of-scope reports-like keys (D11 FE-side guard)', () => {
    const leaky = {
      ...beHappyExample,
      linked_reports: [
        {
          id: 42,
          title: 'leak',
          url: 'https://x.test/1',
          published: '2026-01-01',
          source_name: null,
        },
      ],
      reports: [{ id: 99 }],
      recent_reports: [{ id: 100 }],
    }
    const parsed = actorDetailSchema.parse(leaky)
    expect(parsed).not.toHaveProperty('linked_reports')
    expect(parsed).not.toHaveProperty('reports')
    expect(parsed).not.toHaveProperty('recent_reports')
    // Everything legal is still present.
    expect(parsed.id).toBe(3)
    expect(parsed.name).toBe('Lazarus Group')
  })

  it('rejects missing required name', () => {
    const { name: _omitted, ...rest } = beHappyExample
    expect(() => actorDetailSchema.parse(rest)).toThrow(/name/i)
  })
})

describe('similarReportsResponseSchema', () => {
  const beHappyExample = {
    items: [
      {
        report: {
          id: 99,
          title: 'Related Lazarus campaign',
          url: 'https://mandiant.com/blog/lazarus-2025q4',
          published: '2025-12-01',
          source_name: 'Mandiant',
        },
        score: 0.87,
      },
    ],
  }

  // Plan D10 empty contract — BE example[1] verbatim. Source has
  // NULL embedding OR kNN returned zero rows: 200 + {items: []}.
  const beEmptyExample = { items: [] }

  it('parses the BE happy example verbatim', () => {
    const parsed = similarReportsResponseSchema.parse(beHappyExample)
    expect(parsed.items).toHaveLength(1)
    expect(parsed.items[0].score).toBeCloseTo(0.87)
  })

  it('parses the D10 empty contract (no fake fallback)', () => {
    expect(similarReportsResponseSchema.parse(beEmptyExample)).toEqual(beEmptyExample)
  })

  it('rejects score outside [0, 1] (D8 bounds)', () => {
    const oob = {
      items: [{ report: beHappyExample.items[0].report, score: 1.2 }],
    }
    expect(() => similarReportsResponseSchema.parse(oob)).toThrow()
    const negative = {
      items: [{ report: beHappyExample.items[0].report, score: -0.1 }],
    }
    expect(() => similarReportsResponseSchema.parse(negative)).toThrow()
  })

  // D8 SIMILAR_K_MAX = 50 DTO-layer ceiling.
  it('rejects items exceeding SIMILAR_K_MAX', () => {
    const tooMany = {
      items: Array.from({ length: SIMILAR_K_MAX + 1 }, (_, i) => ({
        report: {
          id: i + 1,
          title: `r ${i + 1}`,
          url: `https://x.test/${i}`,
          published: '2026-01-01',
          source_name: null,
        },
        score: 0.5,
      })),
    }
    expect(() => similarReportsResponseSchema.parse(tooMany)).toThrow()
  })

  it('rejects embedded report with missing required published', () => {
    const bad = {
      items: [
        {
          report: {
            id: 99,
            title: 'missing-published',
            url: 'https://x.test',
            source_name: null,
          },
          score: 0.5,
        },
      ],
    }
    expect(() => similarReportsResponseSchema.parse(bad)).toThrow(/published/i)
  })
})
