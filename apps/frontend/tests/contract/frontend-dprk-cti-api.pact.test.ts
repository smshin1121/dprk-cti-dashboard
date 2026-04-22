/**
 * Pact consumer test — frontend ↔ dprk-cti-api.
 *
 * Plan §4 Group H + §5.3, D8 lock (PR #12) + §4 Group J (PR #13) +
 * PR #14 Group G (+5 interactions for detail routes + similar).
 *
 *   /api/v1/auth/me                           — happy (200) [PR #12]
 *   /api/v1/dashboard/summary                 — happy with filters [PR #12]
 *   /api/v1/actors                            — first page + pagination [PR #12]
 *   /api/v1/auth/logout                       — 204 [PR #12]
 *   /api/v1/analytics/attack_matrix           — happy with filters [PR #13 J]
 *   /api/v1/analytics/trend                   — happy with filters [PR #13 J]
 *   /api/v1/analytics/geo                     — happy with filters [PR #13 J]
 *   /api/v1/reports/{id}                      — detail happy [PR #14 G]
 *   /api/v1/incidents/{id}                    — detail happy [PR #14 G]
 *   /api/v1/actors/{id}                       — detail happy [PR #14 G]
 *   /api/v1/reports/{id}/similar              — populated [PR #14 G]
 *                                              — D10 empty  [PR #14 G]
 *   /api/v1/actors/{id}/reports               — populated [PR #15 F]
 *                                              — D15 empty  [PR #15 F]
 *   /api/v1/search                             — populated   [PR #17 F]
 *                                              — D10 empty   [PR #17 F]
 *                                              — 422 blank q [PR #17 F]
 *
 * Pinned-id strategy for detail + similar + actor-reports paths:
 *   Detail endpoints take the resource id in the PATH. A path-param
 *   regex matcher would skate close to R3 (pact-js V3 FFI has
 *   panicked on regex matchers applied to headers; the path matcher
 *   surface is less tested). The safer approach is to literal-pin
 *   the consumer path at a known fixture id (999001/999002/999003/
 *   999004/999020/999030), and have the BE state handler seed THAT id
 *   specifically via `ON CONFLICT (id) DO NOTHING` upserts. No
 *   regex, no sequence drift, no Lazarus-id coupling. The
 *   constants live in `services/api/src/api/routers/pact_states.py`:
 *   `REPORT_DETAIL_FIXTURE_ID` / `INCIDENT_DETAIL_FIXTURE_ID` /
 *   `ACTOR_DETAIL_FIXTURE_ID` / `ACTOR_WITH_NO_REPORTS_ID` /
 *   `SIMILAR_POPULATED_SOURCE_ID` / `SIMILAR_EMPTY_EMBEDDING_SOURCE_ID`.
 *
 * `/auth/me 401`:
 *   Not in this pact — pact-ruby's Verifier applies
 *   `custom_provider_headers` (the auth cookie) to every
 *   interaction in a single run, which authenticates the 401
 *   request and fails the contract. The 401 path is a FE-side
 *   cache-eviction contract covered by
 *   `useMe.test.tsx::surfaces ApiError 401 as null cached data`.
 *
 * Plan D2 locked shapes (PR #13) — pinned in the three analytics
 * interactions below verbatim:
 *   attack_matrix: { tactics: [{id,name}], rows: [{tactic_id,
 *                    techniques: [{technique_id, count}]}] }
 *   trend:         { buckets: [{month: "YYYY-MM", count}] }
 *   geo:           { countries: [{iso2: string(len=2), count}] }
 *
 * The analytics interactions deliberately omit `group_id` from the
 * wire — the FE runtime does send it, but encoding a specific id
 * into the contract couples the pact to a DB-assigned row id the
 * provider-state handler does not guarantee. See the per-describe
 * block docstrings (Codex R1 P2 note) for detail.
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
    // through the Lazarus codename row. FE AttackHeatmap sends
    // `top_n=30` by default (DEFAULT_TOP_N locked in Group H).
    //
    // WHY NO group_id on this interaction (Codex R1 P2, PR #13):
    //   The pact was initially written with `group_id=['1']` to
    //   mirror the FE AttackHeatmap runtime call. BUT the provider-
    //   state handler only guarantees that Lazarus is SEEDED — it
    //   does NOT guarantee the DB-assigned group id is 1. On a
    //   fresh DB with this as the first interaction the id happens
    //   to be 1, but a reordering (or a future fixture that inserts
    //   another group first) would produce an empty payload under
    //   `group_id=1` while the BE + seed would both still be
    //   correct. Dropping `group_id` decouples the contract from
    //   provider-side row-id assignment; the D2 row-based shape is
    //   still fully exercised via the unfiltered aggregator output.
    provider
      .given('seeded attack_matrix dataset and an authenticated analyst session')
      .uponReceiving(
        'a request for the ATT&CK matrix with date filter and top_n',
      )
      .withRequest({
        method: 'GET',
        path: '/api/v1/analytics/attack_matrix',
        query: {
          date_from: '2026-01-01',
          date_to: '2026-04-18',
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
    // across 2 months (2026-02: 2 reports, 2026-03: 1 report).
    // No `group_id` on the wire — see the attack_matrix block for
    // the Codex R1 P2 rationale (provider-state doesn't guarantee
    // Lazarus id=1; unfiltered contract still exercises the D2
    // monthly-bucket shape).
    provider
      .given('seeded trend dataset and an authenticated analyst session')
      .uponReceiving(
        'a request for the monthly-trend buckets with date filter',
      )
      .withRequest({
        method: 'GET',
        path: '/api/v1/analytics/trend',
        query: {
          date_from: '2026-01-01',
          date_to: '2026-04-18',
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

// ---------------------------------------------------------------------
// /reports/{id} — detail view (PR #14 Group E + Group G)
// ---------------------------------------------------------------------
//
// PINNED FIXTURE ID: 999001 (REPORT_DETAIL_FIXTURE_ID). The BE
// state handler seeds this id via `ON CONFLICT (id) DO NOTHING`
// upsert — consumer + provider agree on the exact path, no regex.

describe('GET /api/v1/reports/{id}', () => {
  it('returns the full report detail with linked_incidents (D9 + D11)', async () => {
    provider
      .given('seeded report detail fixture and an authenticated analyst session')
      .uponReceiving('a request for a report detail by id (PR #14 Group G)')
      .withRequest({
        method: 'GET',
        path: '/api/v1/reports/999001',
      })
      .willRespondWith({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        // Shape matchers — plan D9 payload depth. linked_incidents
        // is eachLike on summary shape (id, title, reported). D11
        // navigation contract: each entry is a summary only, never
        // a full IncidentItem; recursion is forbidden per D9.
        body: like({
          id: integer(999001),
          title: string('Pact fixture — report detail source'),
          url: string('https://pact.test/reports/detail/source'),
          url_canonical: string('https://pact.test/reports/detail/source'),
          published: string('2026-03-15'),
          source_id: integer(1),
          source_name: string('pact-fixture-source'),
          lang: string('en'),
          tlp: string('WHITE'),
          summary: string('Pact fixture body — report detail happy path.'),
          tags: eachLike('pact-detail-tag-a'),
          codenames: eachLike('Andariel'),
          techniques: eachLike('T1566'),
          linked_incidents: eachLike({
            id: integer(18),
            title: string('Pact fixture — report detail linked incident 1'),
            reported: string('2026-02-10'),
          }),
        }),
      })

    await provider.executeTest(async (mockServer) => {
      const res = await fetch(`${mockServer.url}/api/v1/reports/999001`)
      expect(res.status).toBe(200)
      const body = (await res.json()) as {
        id: number
        title: string
        linked_incidents: { id: number; title: string }[]
      }
      expect(body.id).toBeTypeOf('number')
      expect(body.title).toBeTypeOf('string')
      expect(Array.isArray(body.linked_incidents)).toBe(true)
      expect(body.linked_incidents.length).toBeGreaterThan(0)
    })
  })
})

// ---------------------------------------------------------------------
// /incidents/{id} — detail view (PR #14 Group E + Group G)
// ---------------------------------------------------------------------
//
// PINNED FIXTURE ID: 999002 (INCIDENT_DETAIL_FIXTURE_ID).

describe('GET /api/v1/incidents/{id}', () => {
  it('returns the full incident detail with linked_reports (D9 + D11)', async () => {
    provider
      .given('seeded incident detail fixture and an authenticated analyst session')
      .uponReceiving('a request for an incident detail by id (PR #14 Group G)')
      .withRequest({
        method: 'GET',
        path: '/api/v1/incidents/999002',
      })
      .willRespondWith({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        // D9 payload depth — flat motivations / sectors / countries
        // + capped linked_reports (eachLike summary shape). D11
        // navigation: linked_reports rows link to /reports/:id via
        // incident_sources M:N bidirectionally.
        body: like({
          id: integer(999002),
          title: string('Pact fixture — incident detail'),
          reported: string('2024-05-02'),
          description: string('Pact fixture incident description'),
          attribution_confidence: string('HIGH'),
          motivations: eachLike('financial'),
          sectors: eachLike('crypto'),
          countries: eachLike('KR'),
          linked_reports: eachLike({
            id: integer(42),
            title: string('Pact fixture — incident detail linked report'),
            url: string('https://pact.test/reports/linked/1'),
            published: string('2026-03-15'),
            source_name: string('pact-fixture-source'),
          }),
        }),
      })

    await provider.executeTest(async (mockServer) => {
      const res = await fetch(`${mockServer.url}/api/v1/incidents/999002`)
      expect(res.status).toBe(200)
      const body = (await res.json()) as {
        id: number
        linked_reports: { id: number; url: string }[]
      }
      expect(body.id).toBeTypeOf('number')
      expect(Array.isArray(body.linked_reports)).toBe(true)
      expect(body.linked_reports.length).toBeGreaterThan(0)
    })
  })
})

// ---------------------------------------------------------------------
// /actors/{id} — detail view (PR #14 Group E + Group G)
// ---------------------------------------------------------------------
//
// PINNED FIXTURE ID: 999003 (ACTOR_DETAIL_FIXTURE_ID). Previously
// the Group C fixture aliased `_ensure_canonical_lazarus_fixture`
// which DB-assigned the Lazarus id — a consumer path like
// `/actors/1` would break as soon as the sequence put Lazarus
// elsewhere. Group G pins a Pact-specific actor at 999003 so the
// contract is robust to Lazarus natural-id drift.

describe('GET /api/v1/actors/{id}', () => {
  it('returns the actor detail (D11: no linked_reports surface)', async () => {
    provider
      .given('seeded actor detail fixture and an authenticated analyst session')
      .uponReceiving('a request for an actor detail by id (PR #14 Group G)')
      .withRequest({
        method: 'GET',
        path: '/api/v1/actors/999003',
      })
      .willRespondWith({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        // D11 out-of-scope pin: the ActorDetail DTO has NO
        // linked_reports / reports / recent_reports field. This
        // pact does not mention those fields — the BE should not
        // emit them either; FE Zod strips them if it did.
        body: like({
          id: integer(999003),
          name: string('Lazarus Group'),
          mitre_intrusion_set_id: string('G0032'),
          aka: eachLike('APT38'),
          description: string('DPRK-attributed actor description'),
          codenames: eachLike('Andariel'),
        }),
      })

    await provider.executeTest(async (mockServer) => {
      const res = await fetch(`${mockServer.url}/api/v1/actors/999003`)
      expect(res.status).toBe(200)
      const body = (await res.json()) as Record<string, unknown>
      expect(body.id).toBeTypeOf('number')
      expect(body.name).toBeTypeOf('string')
      // D11 regression guard at the consumer level — the provider
      // response must not carry any reports-like surface on actor
      // detail (pact only asserts presence of matched keys, so the
      // consumer test pins absence explicitly).
      expect(body).not.toHaveProperty('linked_reports')
      expect(body).not.toHaveProperty('reports')
      expect(body).not.toHaveProperty('recent_reports')
    })
  })
})

// ---------------------------------------------------------------------
// /reports/{id}/similar — populated + D10 empty (PR #14 Group F + G)
// ---------------------------------------------------------------------
//
// Two distinct interactions share one endpoint shape:
//   - populated: SIMILAR_POPULATED_SOURCE_ID=999020 seeds source +
//     3 neighbors with embeddings. kNN returns 3 non-empty rows.
//   - D10 empty: SIMILAR_EMPTY_EMBEDDING_SOURCE_ID=999030 seeds
//     source WITH NULL embedding + neighbor WITH embedding. The
//     BE's D10 branch returns {items: []} — NOT 500, NOT a fake
//     fallback. Splitting these into separate .given(...) states
//     lets the verifier cleanly exercise both paths without one
//     fixture polluting the other's cache semantics.

describe('GET /api/v1/reports/{id}/similar', () => {
  it('returns populated similar items (D8 + D9)', async () => {
    provider
      .given(
        'seeded similar reports populated fixture '
          + 'and an authenticated analyst session',
      )
      .uponReceiving(
        'a request for similar reports with a populated source (PR #14 Group G)',
      )
      .withRequest({
        method: 'GET',
        path: '/api/v1/reports/999020/similar',
        query: { k: '10' },
      })
      .willRespondWith({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        // D8 shape — items is eachLike on {report, score}. report
        // is LinkedReportSummary; score is [0,1] per SimilarReportEntry.
        body: like({
          items: eachLike({
            report: {
              id: integer(999011),
              title: string('Pact fixture — similar neighbor'),
              url: string('https://pact.test/reports/similar/neighbor-1'),
              published: string('2025-12-01'),
              source_name: string('pact-fixture-source'),
            },
            score: like(0.87),
          }),
        }),
      })

    await provider.executeTest(async (mockServer) => {
      const url = new URL(`${mockServer.url}/api/v1/reports/999020/similar`)
      url.searchParams.set('k', '10')
      const res = await fetch(url.toString())
      expect(res.status).toBe(200)
      const body = (await res.json()) as {
        items: { report: { id: number }; score: number }[]
      }
      expect(Array.isArray(body.items)).toBe(true)
      expect(body.items.length).toBeGreaterThan(0)
      expect(body.items[0].report.id).toBeTypeOf('number')
      // D8 score bounds — float in [0, 1].
      expect(body.items[0].score).toBeGreaterThanOrEqual(0)
      expect(body.items[0].score).toBeLessThanOrEqual(1)
    })
  })

  // Plan D10 empty contract — source has NULL embedding → 200 +
  // {items: []}. NOT 500. NOT a fake fallback. The consumer pact
  // MUST match items as an empty array literal, because eachLike
  // requires ≥1 row at verify time.
  it('returns the D10 empty contract when source has no embedding', async () => {
    provider
      .given(
        'seeded similar reports empty-embedding fixture '
          + 'and an authenticated analyst session',
      )
      .uponReceiving(
        'a request for similar reports with a null-embedding source (PR #14 Group G)',
      )
      .withRequest({
        method: 'GET',
        path: '/api/v1/reports/999030/similar',
        query: { k: '10' },
      })
      .willRespondWith({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        // D10: explicit empty array — no matcher. eachLike would
        // require a non-empty example which the D10 path cannot
        // produce; asserting the literal `[]` is the contract.
        body: { items: [] },
      })

    await provider.executeTest(async (mockServer) => {
      const url = new URL(`${mockServer.url}/api/v1/reports/999030/similar`)
      url.searchParams.set('k', '10')
      const res = await fetch(url.toString())
      expect(res.status).toBe(200)
      const body = (await res.json()) as { items: unknown[] }
      expect(Array.isArray(body.items)).toBe(true)
      expect(body.items).toHaveLength(0)
    })
  })
})

// ---------------------------------------------------------------------
// /actors/{id}/reports — populated + D15 empty (PR #15 Group F)
// ---------------------------------------------------------------------
//
// Plan D1 + D9 + D14 + D15 — the PR #14 D11 carry-over (ActorDetail
// deliberately had no `linked_reports` surface) closes here via a
// SIBLING endpoint, not by enriching `ActorDetail`. The two
// interactions use DISTINCT pinned ids so populated and empty never
// share state:
//   - populated: ACTOR_DETAIL_FIXTURE_ID=999003 (reused from Group G)
//                + 3 reports pinned at ACTOR_REPORTS_FIXTURE_REPORT_IDS
//                (999050/999051/999052) linked via codename. kNN over
//                `report_codenames` produces ≥3 non-empty rows.
//   - D15 empty: ACTOR_WITH_NO_REPORTS_ID=999004 — distinct-name
//                Pact-specific actor with 1 codename but ZERO
//                `report_codenames` rows. BE returns `{items: [],
//                next_cursor: null}` — NOT 404 (the actor exists),
//                NOT a fake "recent N" fallback. The D15(a) 404
//                branch is NOT in this pact — pact-ruby's
//                `custom_provider_headers` authenticates every
//                interaction, so 404 would collide with the happy
//                case just like /auth/me 401 did.
//
// D12 regression carry — the main `/actors/{id}` pact (above) still
// asserts no reports-like surface on the ActorDetail response. This
// pact adds a SEPARATE endpoint; the detail shape stays untouched.

describe('GET /api/v1/actors/{id}/reports', () => {
  // D14 populated — eachLike over the ReportItem shape. Matchers
  // are type-only (integer / string / eachLike), so the fixture's
  // actual seeded values (title "Pact fixture — actor reports #1",
  // published "2026-03-15") satisfy the contract by virtue of being
  // non-empty strings + valid dates.
  it('returns populated linked reports (PR #15 Group F)', async () => {
    provider
      .given(
        'seeded actor with linked reports fixture '
          + 'and an authenticated analyst session',
      )
      .uponReceiving(
        'a request for reports linked to an actor (PR #15 Group F)',
      )
      .withRequest({
        method: 'GET',
        path: '/api/v1/actors/999003/reports',
      })
      .willRespondWith({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        // D9 envelope reuse — {items, next_cursor} ONLY. No
        // `total`, no `limit` echo. Matcher-side: eachLike on
        // items; next_cursor literal null (final page of the
        // seeded 3-row fixture).
        body: like({
          items: eachLike({
            id: integer(999050),
            title: string('Pact fixture — actor reports #1 (newest)'),
            url: string('https://pact.test/actor-reports/999050'),
            url_canonical: string(
              'https://pact.test/actor-reports/999050',
            ),
            published: string('2026-03-15'),
            source_id: integer(1),
            source_name: string('Vendor'),
            lang: string('en'),
            tlp: string('WHITE'),
          }),
          next_cursor: null,
        }),
      })

    await provider.executeTest(async (mockServer) => {
      const res = await fetch(
        `${mockServer.url}/api/v1/actors/999003/reports`,
      )
      expect(res.status).toBe(200)
      const body = (await res.json()) as {
        items: {
          id: number
          title: string
          published: string
        }[]
        next_cursor: string | null
      }
      // D9 envelope — strict key set.
      expect(Object.keys(body).sort()).toEqual(['items', 'next_cursor'])
      expect(Array.isArray(body.items)).toBe(true)
      expect(body.items.length).toBeGreaterThan(0)
      // ReportItem shape — pin the core keys we render in the panel.
      const item = body.items[0]
      expect(item.id).toBeTypeOf('number')
      expect(item.title).toBeTypeOf('string')
      expect(item.published).toBeTypeOf('string')
    })
  })

  // D15(b/c/d) empty — actor exists + has codenames + zero linked
  // reports. Literal empty body — eachLike requires ≥1 example.
  // Distinct pinned actor id so the empty state never collides
  // with the populated one's seed set.
  it('returns the D15 empty contract when no linked reports exist', async () => {
    provider
      .given(
        'seeded actor with no linked reports fixture '
          + 'and an authenticated analyst session',
      )
      .uponReceiving(
        'a request for reports linked to an actor with no links (PR #15 Group F)',
      )
      .withRequest({
        method: 'GET',
        path: '/api/v1/actors/999004/reports',
      })
      .willRespondWith({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        // D15 empty — explicit literal body. D15(a) 404 NOT here;
        // actor 999004 exists (distinct from ACTOR_DETAIL_FIXTURE_ID)
        // so the contract is reachable without colliding with the
        // populated interaction's state setup.
        body: { items: [], next_cursor: null },
      })

    await provider.executeTest(async (mockServer) => {
      const res = await fetch(
        `${mockServer.url}/api/v1/actors/999004/reports`,
      )
      expect(res.status).toBe(200)
      const body = (await res.json()) as {
        items: unknown[]
        next_cursor: string | null
      }
      expect(Array.isArray(body.items)).toBe(true)
      expect(body.items).toHaveLength(0)
      expect(body.next_cursor).toBeNull()
    })
  })
})

// ---------------------------------------------------------------------
// /search — populated + D10 empty + 422 blank-q (PR #17 Group F)
// ---------------------------------------------------------------------
//
// Plan D8 + D9 + D10 — FTS-only MVP. Three interactions pinned:
//
//   populated : GET /api/v1/search?q=lazarus
//     State   : seeded search populated fixture ...
//     Shape   : {items: eachLike(SearchHit), total_hits, latency_ms}
//               SearchHit = {report: ReportItem, fts_rank: number,
//                            vector_rank: integer() matcher}
//     Notes   : PR #19b OI6 = B — vector_rank flipped from literal
//               null to an integer() matcher. The provider-state
//               handler stamps deterministic stub embeddings onto
//               the populated fixture rows (999060..062) so the
//               vector-kNN kicks them into the top-N and the hybrid
//               RRF path populates vector_rank. Envelope top-level
//               keys remain {items, total_hits, latency_ms} — the
//               only change is the per-hit vector_rank matcher
//               shifting from literal to shape. A future BE edit
//               that reverts to returning null would fail the
//               integer() matcher and surface immediately.
//
//   D10 empty : GET /api/v1/search?q=nomatchxyz123
//     State   : seeded search empty fixture ...
//     Shape   : explicit literal {items: [], total_hits: 0,
//               latency_ms: <any int>}
//     Notes   : distractor row (999063) exists in the DB so the
//               empty envelope comes from FTS miss, not DB emptiness.
//               eachLike cannot express empty — literal body only.
//
//   422       : GET /api/v1/search?q=
//     State   : an authenticated analyst session (no seed — 422
//               fires before DB lookup)
//     Shape   : 422 + {detail: [...]}
//     Notes   : FastAPI Query(min_length=1) rejects q='' before the
//               function body runs. The FE hook's enable gate
//               prevents blank q from hitting the wire in practice;
//               this pact pins the server-side contract so any
//               future BE change (e.g. relaxing min_length) that
//               would silently accept blank q flips red.
//
// Why the 422 interaction co-exists with the happy ones:
//   /auth/me 401 could NOT coexist with /auth/me 200 because
//   `custom_provider_headers` injects the session cookie on every
//   request, authenticating the 401 path. The 422 path is NOT
//   auth-gated — it's parameter validation, which fires identically
//   whether the cookie is present or absent. So the happy +
//   422 split is contractually realizable in one pact file.
//
// Pinned-id strategy (consistent with PR #14/#15):
//   Populated hits rows at SEARCH_POPULATED_FIXTURE_REPORT_IDS =
//   (999060, 999061, 999062); empty state seeds a distractor at
//   SEARCH_EMPTY_FIXTURE_REPORT_IDS[0] = 999063. The consumer pact
//   does NOT hardcode those ids in the matcher examples (fts-hit
//   ids are not FE-deterministic in general), but the state handler
//   uses them verbatim so the integer() matcher on `report.id`
//   succeeds against real rows.

describe('GET /api/v1/search', () => {
  it('returns populated search hits for a q that matches (PR #17 Group F)', async () => {
    provider
      .given(
        'seeded search populated fixture '
          + 'and an authenticated analyst session',
      )
      .uponReceiving(
        'a request for search hits against "lazarus" (PR #17 Group F)',
      )
      .withRequest({
        method: 'GET',
        path: '/api/v1/search',
        query: { q: 'lazarus' },
      })
      .willRespondWith({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        // D9 envelope: items + total_hits + latency_ms. eachLike
        // over the SearchHit body; inside each hit, `report` uses
        // like() on the ReportItem shape (matches PR #15 actor-
        // reports style). PR #19b OI6 = B — ``vector_rank`` uses
        // an ``integer()`` matcher now; the provider-state handler
        // stamps deterministic embeddings so the hybrid path returns
        // a 1-indexed int rather than the PR #17 literal null.
        body: like({
          items: eachLike({
            report: like({
              id: integer(999060),
              title: string('Lazarus targets SK crypto exchanges'),
              url: string(
                'https://pact.test/search/populated-999060',
              ),
              url_canonical: string(
                'https://pact.test/search/populated-999060',
              ),
              published: string('2026-03-15'),
              source_id: integer(1),
              source_name: string('Vendor'),
              lang: string('en'),
              tlp: string('WHITE'),
            }),
            fts_rank: like(0.0759),
            // PR #19b OI6 = B — integer() matcher replaces the
            // PR #17 literal null. Validates SHAPE, not VALUE; the
            // BE stamps embeddings on the fixture rows so vector-
            // kNN places them in the top-N and the hybrid RRF path
            // populates a positive 1-indexed rank.
            vector_rank: integer(1),
          }),
          total_hits: integer(3),
          latency_ms: integer(42),
        }),
      })

    await provider.executeTest(async (mockServer) => {
      const url = new URL(`${mockServer.url}/api/v1/search`)
      url.searchParams.set('q', 'lazarus')
      const res = await fetch(url.toString())
      expect(res.status).toBe(200)
      const body = (await res.json()) as {
        items: {
          report: { id: number; title: string }
          fts_rank: number
          vector_rank: number | null
        }[]
        total_hits: number
        latency_ms: number
      }
      // D9 envelope key set — strict.
      expect(Object.keys(body).sort()).toEqual([
        'items',
        'latency_ms',
        'total_hits',
      ])
      expect(Array.isArray(body.items)).toBe(true)
      expect(body.items.length).toBeGreaterThan(0)
      // SearchHit shape — PR #19b OI6 = B: vector_rank is now a
      // positive 1-indexed integer (provider-state stamps stub
      // embeddings so vector-kNN returns a rank for the fixture row).
      const hit = body.items[0]
      expect(hit.report.id).toBeTypeOf('number')
      expect(hit.report.title).toBeTypeOf('string')
      expect(hit.fts_rank).toBeTypeOf('number')
      expect(hit.vector_rank).toBeTypeOf('number')
      expect(hit.vector_rank).not.toBeNull()
      expect(hit.vector_rank as number).toBeGreaterThanOrEqual(1)
    })
  })

  it('returns the D10 empty envelope when q does not match (PR #17 Group F)', async () => {
    provider
      .given(
        'seeded search empty fixture '
          + 'and an authenticated analyst session',
      )
      .uponReceiving(
        'a request for search hits against "nomatchxyz123" (PR #17 Group F)',
      )
      .withRequest({
        method: 'GET',
        path: '/api/v1/search',
        query: { q: 'nomatchxyz123' },
      })
      .willRespondWith({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        // D10 empty — body wrapped in like() so pact-ruby applies
        // the nested integer() matcher on latency_ms. A plain
        // object root (without like()) makes pact-ruby compare the
        // whole body literally, ignoring any nested matcher — which
        // breaks on latency_ms because the actual value is timing-
        // dependent (CI hit `Expected 12 but got 4 at $.latency_ms`
        // on the first pass without the wrapper). Under like() the
        // root is a type-matcher; items: [] still asserts "array
        // type" but the verifier is lenient on array contents when
        // the example is empty, so `actual: []` matches. total_hits
        // stays literal 0 (the only meaningful value for an empty
        // envelope per BE contract).
        body: like({
          items: [],
          total_hits: 0,
          latency_ms: integer(12),
        }),
      })

    await provider.executeTest(async (mockServer) => {
      const url = new URL(`${mockServer.url}/api/v1/search`)
      url.searchParams.set('q', 'nomatchxyz123')
      const res = await fetch(url.toString())
      expect(res.status).toBe(200)
      const body = (await res.json()) as {
        items: unknown[]
        total_hits: number
        latency_ms: number
      }
      expect(Array.isArray(body.items)).toBe(true)
      expect(body.items).toHaveLength(0)
      expect(body.total_hits).toBe(0)
      expect(body.latency_ms).toBeTypeOf('number')
    })
  })

  it('returns 422 for a blank q (PR #17 Group F)', async () => {
    provider
      .given('an authenticated analyst session')
      .uponReceiving(
        'a request for search hits with blank q (PR #17 Group F)',
      )
      .withRequest({
        method: 'GET',
        path: '/api/v1/search',
        query: { q: '' },
      })
      .willRespondWith({
        status: 422,
        headers: { 'Content-Type': 'application/json' },
        // Loose shape — `{detail: eachLike({loc, msg, type})}`.
        // FastAPI's Query(min_length=1) yields Pydantic-v2 shape
        // (`type: 'string_too_short'`) for blank q; the custom
        // `q.strip()` guard (value_error.blank_query) only fires
        // on a whitespace-only q which takes a different code
        // path. Matcher is intentionally loose so either BE
        // implementation detail satisfies the contract without
        // flapping red on a cosmetic msg/type tweak.
        body: like({
          detail: eachLike({
            loc: eachLike('query'),
            msg: string('String should have at least 1 character'),
            type: string('string_too_short'),
          }),
        }),
      })

    await provider.executeTest(async (mockServer) => {
      const url = new URL(`${mockServer.url}/api/v1/search`)
      url.searchParams.set('q', '')
      const res = await fetch(url.toString())
      expect(res.status).toBe(422)
      const body = (await res.json()) as {
        detail: { loc: unknown[]; msg: string; type: string }[]
      }
      expect(Array.isArray(body.detail)).toBe(true)
      expect(body.detail.length).toBeGreaterThan(0)
      expect(body.detail[0].loc).toContain('query')
    })
  })
})

afterAll(() => {
  // PactV3 writes the pact file to `dir` after each executeTest;
  // adding a no-op afterAll lets us hook in additional logging if
  // ever needed, and keeps the file well-formed even if a test
  // throws before reaching its own writePactFile().
})
