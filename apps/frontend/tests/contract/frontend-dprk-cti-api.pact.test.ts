/**
 * Pact consumer test — frontend ↔ dprk-cti-api.
 *
 * Plan §4 Group H + §5.3, D8 lock. Six interactions across four
 * endpoints (the "four interactions" in §5.3 refers to the four
 * endpoints; sub-cases per endpoint are listed in D8):
 *
 *   /api/v1/auth/me          — happy (200) + missing-session (401)
 *   /api/v1/dashboard/summary — happy (200) with date+group filters
 *   /api/v1/actors            — first page + offset pagination
 *   /api/v1/auth/logout       — 204
 *
 * `/reports` + `/incidents` interactions are deferred to PR #13 per
 * D8 lock — see `apps/frontend/tests/contract/README.md` for the
 * follow-up note.
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

  it('returns 401 when no valid session cookie is present', async () => {
    provider
      .given('no valid session cookie')
      .uponReceiving('a request for the current user without a session')
      .withRequest({
        method: 'GET',
        path: '/api/v1/auth/me',
      })
      .willRespondWith({
        status: 401,
        headers: { 'Content-Type': 'application/json' },
        body: like({ detail: string('not authenticated') }),
      })

    await provider.executeTest(async (mockServer) => {
      const res = await fetch(`${mockServer.url}/api/v1/auth/me`)
      expect(res.status).toBe(401)
    })
  })
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
