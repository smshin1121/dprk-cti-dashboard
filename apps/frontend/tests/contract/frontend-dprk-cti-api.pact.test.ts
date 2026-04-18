/**
 * Pact consumer test — frontend ↔ dprk-cti-api.
 *
 * Plan §4 Group H + §5.3, D8 lock (PR #12) + §4 Group J (PR #13).
 * Seven endpoints total; the `/api/v1/auth/me 401` sub-case in D8
 * is covered by the FE unit test `useMe.test.tsx::surfaces
 * ApiError 401 as null cached data` (it pins the queryCache
 * onError handler end-to-end). It is NOT included in the consumer
 * pact because pact-ruby's verifier applies
 * `custom_provider_headers` (the auth cookie) to every interaction
 * in a single run, which would authenticate the 401 request and
 * fail the contract. The 401 path is a FE-side cache behavior
 * contract, not an HTTP-shape contract, so Vitest is the right
 * home.
 *
 *   /api/v1/auth/me                — happy (200)  [PR #12]
 *   /api/v1/dashboard/summary       — happy (200) with filters [PR #12]
 *   /api/v1/actors                  — first page + offset pagination [PR #12]
 *   /api/v1/auth/logout             — 204  [PR #12]
 *   /api/v1/analytics/attack_matrix — happy (200) with filters [PR #13 J]
 *   /api/v1/analytics/trend         — happy (200) with filters [PR #13 J]
 *   /api/v1/analytics/geo           — happy (200) with filters [PR #13 J]
 *
 * Plan D2 locked shapes (PR #13) — pinned in the three analytics
 * interactions below verbatim:
 *   attack_matrix: { tactics: [{id,name}], rows: [{tactic_id,
 *                    techniques: [{technique_id, count}]}] }
 *   trend:         { buckets: [{month: "YYYY-MM", count}] }
 *   geo:           { countries: [{iso2: string(len=2), count}] }
 *
 * `/reports` + `/incidents` interactions remain FE-types-only by
 * plan D7 carry-forward; live verify still covers them via the
 * `contract-verify` CI job indirectly through the shared session.
 *
 * Output:
 * Pact V3 JSON written to `contracts/pacts/frontend-dprk-cti-api.json`
 * (relative to repo root). The file is consumed by the BE
 * `contract-verify` job, which runs pact-python's Verifier against
 * a live uvicorn (PR #11 Group I baseline; Group I in PR #12 flips
 * the verifier from skip-with-ok to live).
 *
 * Why we use raw fetch instead of the FE `getMe()` / `listActors()`
 * helpers:
 * The contract is on the HTTP wire, not on which JS function makes
 * the call. The FE config module (`src/config.ts`) reads `apiUrl`
 * once at module load, which makes per-test redirection awkward.
 * Using raw fetch with `${mockServer.url}/api/v1/...` exercises the
 * exact wire shape the FE helpers produce — same path, same query
 * params, same response handling.
 */

import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { MatchersV3, PactV3 } from '@pact-foundation/pact'
import { afterAll, describe, expect, it } from 'vitest'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const pactDir = path.resolve(__dirname, '../../../../contracts/pacts')

const provider = new PactV3({
  consumer: 'frontend',
  provider: 'dprk-cti-api',
  dir: pactDir,
  // logLevel default 'info' is noisy under vitest; bump to 'warn'.
  logLevel: 'warn',
})

const { like, eachLike, integer, string } = MatchersV3

// ---------------------------------------------------------------------
// /auth/me
// ---------------------------------------------------------------------

describe('GET /api/v1/auth/me', () => {
  it('returns the current user when an authenticated session cookie is present', async () => {
    provider
      .given('an authenticated analyst session')
      .uponReceiving('a request for the current user')
      .withRequest({
        method: 'GET',
        path: '/api/v1/auth/me',
      })
      .willRespondWith({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: like({
          sub: string('kc-uuid-analyst'),
          email: string('analyst@dprk.test'),
          name: string('Jane Analyst'),
          roles: eachLike('analyst'),
        }),
      })

    await provider.executeTest(async (mockServer) => {
      const res = await fetch(`${mockServer.url}/api/v1/auth/me`)
      expect(res.status).toBe(200)
      const body = (await res.json()) as { email: string; roles: string[] }
      expect(body.email).toBeTypeOf('string')
      expect(body.roles).toBeInstanceOf(Array)
    })
  })

  // 401 case intentionally NOT included — see file header. The
  // `useMe.test.tsx::surfaces ApiError 401 as null cached data via
  // queryCache handler` unit test covers the FE cache-eviction
  // contract end-to-end without requiring the live verifier to
  // toggle auth state mid-run.
})

// ---------------------------------------------------------------------
// /dashboard/summary
// ---------------------------------------------------------------------

describe('GET /api/v1/dashboard/summary', () => {
  it('returns aggregate KPIs filtered by date range and group_id', async () => {
    provider
      .given('seeded reports/incidents/actors and an authenticated analyst session')
      .uponReceiving('a request for the dashboard summary with filters')
      .withRequest({
        method: 'GET',
        path: '/api/v1/dashboard/summary',
        query: {
          date_from: '2026-01-01',
          date_to: '2026-04-18',
          // BE accepts repeatable group_id; pact V3 accepts arrays here.
          group_id: ['1', '3'],
        },
      })
      .willRespondWith({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: like({
          total_reports: integer(1204),
          total_incidents: integer(154),
          total_actors: integer(12),
          reports_by_year: eachLike({
            year: integer(2024),
            count: integer(318),
          }),
          incidents_by_motivation: eachLike({
            motivation: string('financial'),
            count: integer(81),
          }),
          top_groups: eachLike({
            group_id: integer(3),
            name: string('Lazarus Group'),
            report_count: integer(412),
          }),
        }),
      })

    await provider.executeTest(async (mockServer) => {
      const url = new URL(`${mockServer.url}/api/v1/dashboard/summary`)
      url.searchParams.append('date_from', '2026-01-01')
      url.searchParams.append('date_to', '2026-04-18')
      url.searchParams.append('group_id', '1')
      url.searchParams.append('group_id', '3')
      const res = await fetch(url.toString())
      expect(res.status).toBe(200)
      const body = (await res.json()) as {
        total_reports: number
        top_groups: { group_id: number }[]
      }
      expect(typeof body.total_reports).toBe('number')
      expect(body.top_groups[0].group_id).toBeTypeOf('number')
    })
  })
})

// ---------------------------------------------------------------------
// /actors — happy + pagination
// ---------------------------------------------------------------------

describe('GET /api/v1/actors', () => {
  it('returns the first page of actors with offset pagination metadata', async () => {
    provider
      .given('seeded actors and an authenticated session')
      .uponReceiving('a request for the actors list (first page)')
      .withRequest({
        method: 'GET',
        path: '/api/v1/actors',
        query: { limit: '50', offset: '0' },
      })
      .willRespondWith({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: like({
          items: eachLike({
            id: integer(3),
            name: string('Lazarus Group'),
            mitre_intrusion_set_id: string('G0032'),
            aka: eachLike('APT38'),
            description: string('DPRK-attributed group'),
            codenames: eachLike('Andariel'),
          }),
          limit: integer(50),
          offset: integer(0),
          total: integer(12),
        }),
      })

    await provider.executeTest(async (mockServer) => {
      const url = new URL(`${mockServer.url}/api/v1/actors`)
      url.searchParams.set('limit', '50')
      url.searchParams.set('offset', '0')
      const res = await fetch(url.toString())
      expect(res.status).toBe(200)
      const body = (await res.json()) as {
        items: unknown[]
        limit: number
        offset: number
        total: number
      }
      expect(body.items.length).toBeGreaterThan(0)
      expect(body.limit).toBeTypeOf('number')
      expect(body.total).toBeTypeOf('number')
    })
  })

  it('returns a subsequent page when offset advances past the first page', async () => {
    provider
      .given('seeded actors with at least 100 rows and an authenticated session')
      .uponReceiving('a request for the actors list (second page)')
      .withRequest({
        method: 'GET',
        path: '/api/v1/actors',
        query: { limit: '50', offset: '50' },
      })
      .willRespondWith({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: like({
          items: eachLike({
            id: integer(99),
            name: string('Some Actor'),
            mitre_intrusion_set_id: string('G9999'),
            aka: eachLike('alias'),
            description: string('description'),
            codenames: eachLike('codename'),
          }),
          limit: integer(50),
          offset: integer(50),
          total: integer(120),
        }),
      })

    await provider.executeTest(async (mockServer) => {
      const url = new URL(`${mockServer.url}/api/v1/actors`)
      url.searchParams.set('limit', '50')
      url.searchParams.set('offset', '50')
      const res = await fetch(url.toString())
      expect(res.status).toBe(200)
      const body = (await res.json()) as { offset: number }
      expect(body.offset).toBe(50)
    })
  })
})

// ---------------------------------------------------------------------
// /analytics/attack_matrix — plan D2 row-based shape (PR #13 Group J)
// ---------------------------------------------------------------------

describe('GET /api/v1/analytics/attack_matrix', () => {
  it('returns the row-based tactic × technique matrix for the filter window', async () => {
    // BE state handler: `_ensure_attack_matrix_fixture` in
    // `services/api/src/api/routers/pact_states.py`. Seeds
    // TA0001: {T1566: 2, T1190: 1} and TA0002: {T1059: 1} linked
    // through Lazarus (group_id=1). FE AttackHeatmap sends
    // `top_n=30` by default (DEFAULT_TOP_N locked in Group H).
    provider
      .given('seeded attack_matrix dataset and an authenticated analyst session')
      .uponReceiving(
        'a request for the ATT&CK matrix with date + group filters and top_n',
      )
      .withRequest({
        method: 'GET',
        path: '/api/v1/analytics/attack_matrix',
        query: {
          date_from: '2026-01-01',
          date_to: '2026-04-18',
          group_id: ['1'],
          top_n: '30',
        },
      })
      .willRespondWith({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        // Plan D2 row-based shape — tactics[] + rows[{tactic_id,
        // techniques[{technique_id, count}]}]. eachLike rejects
        // empty arrays (see pact_fixture_shape memory); the BE
        // fixture guarantees ≥1 tactic, ≥1 row, ≥1 technique per
        // row, so matcher + seed are aligned.
        body: like({
          tactics: eachLike({
            id: string('TA0001'),
            name: string('Initial Access'),
          }),
          rows: eachLike({
            tactic_id: string('TA0001'),
            techniques: eachLike({
              technique_id: string('T1566'),
              count: integer(2),
            }),
          }),
        }),
      })

    await provider.executeTest(async (mockServer) => {
      const url = new URL(`${mockServer.url}/api/v1/analytics/attack_matrix`)
      url.searchParams.append('date_from', '2026-01-01')
      url.searchParams.append('date_to', '2026-04-18')
      url.searchParams.append('group_id', '1')
      url.searchParams.append('top_n', '30')
      const res = await fetch(url.toString())
      expect(res.status).toBe(200)
      const body = (await res.json()) as {
        tactics: { id: string; name: string }[]
        rows: {
          tactic_id: string
          techniques: { technique_id: string; count: number }[]
        }[]
      }
      // Row-based invariant: rows is an array of tactic rows, NOT a
      // sparse (tactic, technique, count) tuple list. The FE
      // AttackHeatmap consumes this verbatim (no client re-pivot).
      expect(Array.isArray(body.rows)).toBe(true)
      expect(body.rows[0].tactic_id).toBeTypeOf('string')
      expect(Array.isArray(body.rows[0].techniques)).toBe(true)
      expect(body.rows[0].techniques[0].technique_id).toBeTypeOf('string')
      expect(body.rows[0].techniques[0].count).toBeTypeOf('number')
    })
  })
})

// ---------------------------------------------------------------------
// /analytics/trend — plan D2 monthly bucket shape (PR #13 Group J)
// ---------------------------------------------------------------------

describe('GET /api/v1/analytics/trend', () => {
  it('returns monthly-bucket counts matching YYYY-MM for the filter window', async () => {
    // BE state handler: `_ensure_trend_fixture`. Seeds 3 reports
    // across 2 months (2026-02: 2 reports, 2026-03: 1 report) so
    // the response has ≥2 buckets even under a group filter.
    provider
      .given('seeded trend dataset and an authenticated analyst session')
      .uponReceiving(
        'a request for the monthly-trend buckets with date + group filters',
      )
      .withRequest({
        method: 'GET',
        path: '/api/v1/analytics/trend',
        query: {
          date_from: '2026-01-01',
          date_to: '2026-04-18',
          group_id: ['1'],
        },
      })
      .willRespondWith({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        // Plan D2 monthly-bucket shape. The `month` field is
        // matched as a string whose example is the zero-padded
        // YYYY-MM format — the FE Zod schema enforces the exact
        // regex on ingest (see `trendBucketSchema` in
        // `apps/frontend/src/lib/api/schemas.ts`), so the contract
        // side uses the simpler `string` matcher plus an example
        // that pins the expected format for reviewers.
        body: like({
          buckets: eachLike({
            month: string('2026-02'),
            count: integer(2),
          }),
        }),
      })

    await provider.executeTest(async (mockServer) => {
      const url = new URL(`${mockServer.url}/api/v1/analytics/trend`)
      url.searchParams.append('date_from', '2026-01-01')
      url.searchParams.append('date_to', '2026-04-18')
      url.searchParams.append('group_id', '1')
      const res = await fetch(url.toString())
      expect(res.status).toBe(200)
      const body = (await res.json()) as {
        buckets: { month: string; count: number }[]
      }
      expect(Array.isArray(body.buckets)).toBe(true)
      expect(body.buckets[0].month).toBeTypeOf('string')
      // YYYY-MM must be 7 chars exactly — cheap sanity on the
      // wire shape without pushing regex matchers into pact.
      expect(body.buckets[0].month).toHaveLength(7)
      expect(body.buckets[0].count).toBeTypeOf('number')
    })
  })
})

// ---------------------------------------------------------------------
// /analytics/geo — plan D2 + D7 plain country rows (PR #13 Group J)
// ---------------------------------------------------------------------

describe('GET /api/v1/analytics/geo', () => {
  it('returns per-country aggregates keyed by ISO2 (KP is a plain row)', async () => {
    // BE state handler: `_ensure_geo_fixture`. Seeds 3 incidents
    // in KR + US + KP inside the pact window. Plan D7 invariant:
    // DPRK (KP) appears as a plain row; the FE owns the highlight
    // layer. group_id is accepted but is a no-op for /geo (see
    // `toGeoQueryParams` + the BE aggregator's schema comment).
    provider
      .given('seeded geo dataset and an authenticated analyst session')
      .uponReceiving(
        'a request for the per-country aggregate with date filters',
      )
      .withRequest({
        method: 'GET',
        path: '/api/v1/analytics/geo',
        query: {
          date_from: '2026-01-01',
          date_to: '2026-04-18',
        },
      })
      .willRespondWith({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        // Plan D2 geo shape — plain `{iso2, count}` rows. No
        // DPRK-special-case field. ISO2 is always 2 chars (enforced
        // by BE regex + FE Zod `length(2)`), so the example fixes a
        // readable row for reviewers.
        body: like({
          countries: eachLike({
            iso2: string('KP'),
            count: integer(1),
          }),
        }),
      })

    await provider.executeTest(async (mockServer) => {
      const url = new URL(`${mockServer.url}/api/v1/analytics/geo`)
      url.searchParams.append('date_from', '2026-01-01')
      url.searchParams.append('date_to', '2026-04-18')
      const res = await fetch(url.toString())
      expect(res.status).toBe(200)
      const body = (await res.json()) as {
        countries: { iso2: string; count: number }[]
      }
      expect(Array.isArray(body.countries)).toBe(true)
      expect(body.countries[0].iso2).toBeTypeOf('string')
      expect(body.countries[0].iso2).toHaveLength(2)
      expect(body.countries[0].count).toBeTypeOf('number')
    })
  })
})

// ---------------------------------------------------------------------
// /auth/logout
// ---------------------------------------------------------------------

describe('POST /api/v1/auth/logout', () => {
  it('returns 204 No Content when the session cookie is cleared', async () => {
    provider
      .given('an authenticated analyst session')
      .uponReceiving('a request to log out')
      .withRequest({
        method: 'POST',
        path: '/api/v1/auth/logout',
      })
      .willRespondWith({
        status: 204,
      })

    await provider.executeTest(async (mockServer) => {
      const res = await fetch(`${mockServer.url}/api/v1/auth/logout`, {
        method: 'POST',
      })
      expect(res.status).toBe(204)
    })
  })
})

afterAll(() => {
  // PactV3 writes the pact file to `dir` after each executeTest;
  // adding a no-op afterAll lets us hook in additional logging if
  // ever needed, and keeps the file well-formed even if a test
  // throws before reaching its own writePactFile().
})
