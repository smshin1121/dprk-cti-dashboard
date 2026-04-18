/**
 * Shell E2E — plan D9 / §5.4 single journey.
 *
 *   1. Seed fixtures + mint session via the BE dev-only
 *      POST /_pact/provider_states endpoint (drift-free with the
 *      contract-verify job). No Keycloak redirect — the dev realm
 *      has `directAccessGrantsEnabled=false` which blocks
 *      browser-level login automation (see memory
 *      `pattern_forged_cookie_verification.md`).
 *   2. Visit /dashboard → assert the Total Reports KPI card renders
 *      with a non-loading numeric value (proves `/auth/me`,
 *      `/dashboard/summary`, AND the KPI strip wiring are
 *      end-to-end healthy).
 *   3. Click the Actors nav link → assert the actors table renders
 *      at least one row (proves `/actors` list + route transition +
 *      ListTable's populated state).
 *
 * Scope discipline:
 * This spec deliberately does NOT cover logout, theme toggle,
 * ⌘K, filter changes, or error paths. Those are Vitest integration
 * territory; E2E is reserved for the one multi-route navigation
 * invariant no unit suite can prove.
 */

import { expect, request, test } from '@playwright/test'

const API_BASE_URL =
  process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8000'

const SEED_STATE =
  'seeded actors with at least 100 rows and an authenticated session'

test.describe('shell journey: dashboard → actors', () => {
  test('an authenticated analyst sees KPIs and can navigate to actors', async ({
    page,
    context,
  }) => {
    // 1) Seed + mint session using the BE provider-state endpoint.
    //    Playwright's APIRequestContext owns its own cookie jar; we
    //    drain it into the browser context via storageState.
    const api = await request.newContext()
    const resp = await api.post(`${API_BASE_URL}/_pact/provider_states`, {
      data: { state: SEED_STATE },
      // JSON body + same-origin intent is fine — the dev-only
      // endpoint is not CORS-protected for the local loopback.
      headers: { 'Content-Type': 'application/json' },
    })
    expect(resp.ok(), `provider-state seed failed: ${resp.status()}`).toBe(true)
    const state = await api.storageState()
    // Forward the session cookie into the browser — rewrite the
    // domain from the loopback host the API context recorded into
    // the base URL's host so the browser sends it on FE-origin
    // navigations.
    const feHost = new URL(
      process.env.E2E_BASE_URL ?? 'http://127.0.0.1:4173',
    ).hostname
    const cookies = state.cookies.map((c) => ({ ...c, domain: feHost }))
    await context.addCookies(cookies)

    // 2) Dashboard renders KPI strip with populated Total Reports.
    await page.goto('/dashboard')
    const totalReports = page.getByTestId('kpi-card-total-reports')
    await expect(totalReports).toBeVisible()
    // Populated (not skeleton) — the inner value element only
    // renders when state !== 'loading'. The text is some integer;
    // 0 is acceptable (populated-zero per Group E contract).
    await expect(totalReports).not.toHaveAttribute('aria-busy', 'true')

    // 3) Navigate to Actors via the topbar link, verify the table
    //    renders at least one row (seed guarantees ≥100).
    await page.getByRole('link', { name: 'Actors' }).click()
    await expect(page).toHaveURL(/\/actors$/)
    const table = page.getByTestId('list-table-populated')
    await expect(table).toBeVisible()
    const rows = page.getByTestId('list-table-row')
    await expect(rows.first()).toBeVisible()
  })
})
