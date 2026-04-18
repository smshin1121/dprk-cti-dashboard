/**
 * URL-state deep-link E2E (PR #13 Group J optional extension).
 *
 * **Scope lock — plan D4 URL-state contract ONLY.** This spec verifies
 * two things and nothing else:
 *
 *   1. Deep-link → store hydration. A URL carrying the plan-D4
 *      whitelisted keys (`date_from`, `date_to`, `group_id`) hydrates
 *      the filter UI on mount.
 *   2. Store change → URL encode. Editing a filter input emits a URL
 *      update via the 3-phase hook's emit effect (Group E).
 *
 * Explicit non-goals (to keep scope from creeping):
 *   - Viz rendering assertions (covered by vitest per-component tests).
 *   - Data-shape assertions (covered by Zod schemas + pact).
 *   - View / tab URL keys (only flow on `/dashboard` and only when the
 *     user changes subview; out of scope for this contract check).
 *   - TLP URL-state negative tests (covered by vitest
 *      `urlState.test.ts` + `useFilterUrlSync.test.tsx`).
 *   - Logout / theme / ⌘K (covered by vitest / existing E2E).
 *
 * Session-seed strategy:
 * Reuses the same `/_pact/provider_states` bootstrapping pattern
 * the existing shell journey uses (drift-free with the
 * contract-verify path). The `seeded actors...` state is sufficient
 * — we only need a valid authenticated session, not a specific
 * analytics payload.
 */

import { expect, request, test } from '@playwright/test'

const API_BASE_URL = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8000'
const FE_BASE_URL = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:4173'

const SEED_STATE =
  'seeded actors with at least 100 rows and an authenticated session'

const DEEP_LINK_DATE_FROM = '2026-01-01'
const DEEP_LINK_DATE_TO = '2026-04-18'

test.describe('URL-state deep-link (plan D4 contract)', () => {
  test.beforeEach(async ({ context }) => {
    // Shared seed step — mints the signed session cookie via the
    // dev-only provider-state endpoint, forwards it into the
    // browser context rewritten to the FE host.
    const api = await request.newContext()
    const resp = await api.post(`${API_BASE_URL}/_pact/provider_states`, {
      data: { state: SEED_STATE },
      headers: { 'Content-Type': 'application/json' },
    })
    expect(resp.ok(), `provider-state seed failed: ${resp.status()}`).toBe(true)
    const state = await api.storageState()
    const feHost = new URL(FE_BASE_URL).hostname
    const cookies = state.cookies.map((c) => ({ ...c, domain: feHost }))
    await context.addCookies(cookies)
  })

  test('deep-link URL hydrates the filter inputs on mount', async ({ page }) => {
    // Visit /dashboard WITH all 3 whitelisted filter keys. The
    // decode + useLayoutEffect hydrate phase of `useFilterUrlSync`
    // runs on the shell's mount (hook fires from Shell.tsx); the
    // FilterBar then renders with the hydrated values.
    await page.goto(
      `/dashboard?date_from=${DEEP_LINK_DATE_FROM}&date_to=${DEEP_LINK_DATE_TO}&group_id=1`,
    )

    const dateFromInput = page.getByTestId('filter-date-from')
    const dateToInput = page.getByTestId('filter-date-to')

    await expect(dateFromInput).toHaveValue(DEEP_LINK_DATE_FROM)
    await expect(dateToInput).toHaveValue(DEEP_LINK_DATE_TO)
  })

  test('changing a filter input updates the URL (emit effect)', async ({
    page,
  }) => {
    // Start from a clean URL with no filter keys — the emit effect's
    // isInitialMountRef guard swallows the first tick; subsequent
    // input changes drive a replaceState that carries the encoded
    // state into the URL.
    await page.goto('/dashboard')

    const dateFromInput = page.getByTestId('filter-date-from')
    await dateFromInput.fill(DEEP_LINK_DATE_FROM)
    // Blur to commit the native <input type="date"> change event;
    // zustand store updates on that event, then the emit effect
    // hops on the next render tick.
    await dateFromInput.blur()

    await expect(page).toHaveURL(
      new RegExp(`date_from=${DEEP_LINK_DATE_FROM}`),
    )
  })
})
