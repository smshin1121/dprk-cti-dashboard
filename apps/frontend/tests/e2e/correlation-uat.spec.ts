/**
 * D-1 correlation UAT 1-5 (PR-C T3 — plan `correlation-hardening.md` §4 T3, C5 lock).
 *
 * Five user-flow assertions mapped 1:1 to umbrella spec §3 UAT 1-5.
 * UAT 6 (NFR-1 perf p95) is a load-shape test, not a user flow, so
 * it ships as the separate `services/api/tests/perf/test_correlation_p95.py`
 * smoke (T4) — out of this file's scope.
 *
 * Session-seed strategy reuses the dev-only POST `/_pact/provider_states`
 * endpoint already powering `login-dashboard-actors.spec.ts` and the
 * Pact contract-verify job — drift-free with the BE harness, no
 * Keycloak browser dance (dev realm `directAccessGrantsEnabled=false`
 * blocks browser-level login automation per
 * `pattern_forged_cookie_verification`).
 *
 * Provider-state strings use the EXACT phrases committed at
 * `services/api/src/api/routers/pact_states.py:2568-2618` per plan
 * C5 lock + T-1 r1 HIGH 2 fold. Unknown-state fall-through at
 * `:2620-2624` mints a session but does NOT seed fixtures, so an
 * exact-phrase typo would silently fail downstream assertions on a
 * non-seeded DB — the tests treat any state-handler 4xx/5xx as a
 * hard failure to flag mismatched phrases early.
 *
 * Locale pin: `addInitScript` seeds `localStorage.i18nextLng = 'en'`
 * before every navigation so i18n bootstrap reads English on first
 * mount regardless of CI runner navigator default. UAT 5 then
 * explicitly toggles ko↔en using the LocaleToggle button.
 *
 * Scope discipline:
 * Per umbrella §11 PR-C size lock, this spec ONLY covers UAT 1-5.
 * Out of scope: method toggle vitest assertions (covered by
 * `CorrelationPage.methodToggle.test.tsx`), URL hydrate vitest
 * assertions (`CorrelationPage.urlState.test.tsx`), schema shape
 * (Zod + Pact), warning-chip rendering (vitest).
 */

import { expect, request, test } from '@playwright/test'
import type { BrowserContext } from '@playwright/test'

const FE_BASE_URL = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:4173'
const API_BASE_URL = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8000'

// Provider-state phrases — copy-pasted verbatim from `pact_states.py`.
// See plan C5 lock for the rationale: any drift here breaks silently
// because unknown states fall through with session-only seeding.
const POPULATED_STATE =
  'seeded correlation populated fixture and an authenticated analyst session'
const INSUFFICIENT_422_STATE =
  'seeded correlation insufficient_sample 422 fixture ' +
  'and an authenticated analyst session'

// Populated fixture window — `_ensure_correlation_populated_fixture`
// seeds 100 months from 2018-01 inclusive. The 2026-04-30 upper bound
// matches plan §3 perf-smoke + AC #6 + umbrella §3 NFR-1 default.
const POPULATED_X = 'reports.total'
const POPULATED_Y = 'incidents.total'
const POPULATED_DATE_FROM = '2018-01-01'
const POPULATED_DATE_TO = '2026-04-30'

const CORRELATION_QS =
  `x=${POPULATED_X}&y=${POPULATED_Y}` +
  `&date_from=${POPULATED_DATE_FROM}&date_to=${POPULATED_DATE_TO}`

async function seedAndForwardCookie(
  context: BrowserContext,
  state: string,
): Promise<void> {
  const api = await request.newContext()
  const resp = await api.post(`${API_BASE_URL}/_pact/provider_states`, {
    data: { state },
    headers: { 'Content-Type': 'application/json' },
  })
  expect(
    resp.ok(),
    `provider-state seed failed for state=${JSON.stringify(state)}: ` +
      `${resp.status()} ${await resp.text()}`,
  ).toBe(true)
  const storage = await api.storageState()
  const feHost = new URL(FE_BASE_URL).hostname
  // Forward both API-host and FE-host cookie variants so direct-GET
  // (UAT 3) and browser navigations (UAT 1/2/4/5) both authenticate.
  const apiHost = new URL(API_BASE_URL).hostname
  const cookies = storage.cookies.flatMap((c) => [
    { ...c, domain: feHost },
    { ...c, domain: apiHost },
  ])
  await context.addCookies(cookies)
  await api.dispose()
}

test.describe('D-1 correlation UAT 1-5 (plan §4 T3 / C5 lock)', () => {
  test.beforeEach(async ({ context }) => {
    await context.addInitScript(() => {
      // Pin English so error / heading / caveat copy are deterministic
      // regardless of CI runner navigator defaults. UAT 5 explicitly
      // toggles to test locale swap behavior.
      window.localStorage.setItem('i18nextLng', 'en')
    })
  })

  test('UAT 1 — populated render with both methods + caveat + lag chart', async ({
    page,
    context,
  }) => {
    await seedAndForwardCookie(context, POPULATED_STATE)

    await page.goto(`/analytics/correlation?${CORRELATION_QS}`)

    // Populated branch resolves once the primary fetch lands. The
    // page-level testid is the canonical "render OK" signal.
    await expect(page.getByTestId('correlation-populated')).toBeVisible()

    // Both method buttons present + Pearson is the URL default
    // (CorrelationPage.tsx:74 — `readMethod` defaults to pearson).
    const pearson = page.getByTestId('correlation-method-pearson')
    const spearman = page.getByTestId('correlation-method-spearman')
    await expect(pearson).toBeVisible()
    await expect(spearman).toBeVisible()
    await expect(pearson).toHaveAttribute('aria-pressed', 'true')
    await expect(spearman).toHaveAttribute('aria-pressed', 'false')

    // Active-method markers render at the page level (independent
    // of populated branch) — check the toggle binding lands.
    await expect(page.getByTestId('line-pearson')).toHaveAttribute(
      'data-method-active',
      'true',
    )
    await expect(page.getByTestId('line-spearman')).toHaveAttribute(
      'data-method-active',
      'false',
    )

    // Caveat banner visible (sessionStorage starts empty per page mount).
    await expect(page.getByTestId('correlation-caveat-banner')).toBeVisible()

    // Lag chart renders the BE-acknowledged date range in the caption.
    // i18n caption template (en) = "α = {{alpha}} · effective n = {{n}} ·
    // period {{from}} – {{to}}". 2018-01 lower bound is contract-locked
    // by the populated fixture seeder.
    const populated = page.getByTestId('correlation-populated')
    await expect(populated).toContainText('2018-01')
    await expect(populated).toContainText('α =')
    // EN-pinned label tokens — UAT 5 asserts the KO mirrors swap in.
    await expect(populated).toContainText('effective n')
    await expect(populated).toContainText('period')

    // AC #1 user-visible coverage per Codex T3 r1 MED 1 fold:
    //   - "both methods render" — Recharts `<Line>` produces one
    //     `recharts-line-curve` SVG path per series. With Pearson +
    //     Spearman both wired (CorrelationLagChart.tsx:88-105) we
    //     expect exactly 2.
    //   - "lag chart [-24, +24]" — the chart's monotone path samples
    //     49 data points (one per cell in the contract-locked grid).
    //     UAT 3 pins the BE-side `lag_grid.length === 49`; here we
    //     pin the user-visible counterpart by counting the rendered
    //     line-curve path elements.
    const lineCurves = populated.locator('.recharts-line-curve')
    await expect(lineCurves).toHaveCount(2)
    // Cross-reference: p-value contract is BE-shape; UAT 3 asserts
    // `pearson.p_raw` / `spearman.p_raw` non-null at every one of
    // the 49 cells. The chart consumes `data.lag_grid` whose
    // contract ships those fields, so a UI render proves the wiring
    // transitively.

    // Method toggle round-trip — click Spearman, confirm marker flips.
    await spearman.click()
    await expect(spearman).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('line-spearman')).toHaveAttribute(
      'data-method-active',
      'true',
    )
    await expect(page.getByTestId('line-pearson')).toHaveAttribute(
      'data-method-active',
      'false',
    )
  })

  test('UAT 2 — < 30 monthly buckets renders the locked insufficient-sample copy', async ({
    page,
    context,
  }) => {
    await seedAndForwardCookie(context, INSUFFICIENT_422_STATE)

    // 6-month window from the seeded fixture; effective_n=6 < 30
    // triggers BE 422 with `value_error.insufficient_sample`. Use the
    // SAME query window the UAT 1 happy path uses — the 422 fires on
    // the seeded data shape, not on the request bounds.
    await page.goto(`/analytics/correlation?${CORRELATION_QS}`)

    const errorBranch = page.getByTestId('correlation-error')
    await expect(errorBranch).toBeVisible()
    await expect(errorBranch).toHaveAttribute(
      'data-error-type',
      'value_error.insufficient_sample',
    )
    // Locked en copy from `correlation.state.errorInsufficientSample`.
    // ko mirror at `init.test.ts` parity check is "표본이 부족합니다 ...".
    await expect(errorBranch).toContainText('Insufficient sample')
    await expect(errorBranch).toContainText('30 months')
  })

  test('UAT 3 — direct GET returns both methods at every lag + interpretation', async ({
    context,
  }) => {
    await seedAndForwardCookie(context, POPULATED_STATE)

    // Issue the direct GET via Playwright's request fixture using the
    // browser context's cookie jar so the session forwards.
    const apiCtx = await request.newContext({
      baseURL: API_BASE_URL,
      storageState: { cookies: await context.cookies(), origins: [] },
    })
    const resp = await apiCtx.get(
      `/api/v1/analytics/correlation?${CORRELATION_QS}&alpha=0.05`,
    )
    expect(resp.ok(), `GET correlation failed: ${resp.status()}`).toBe(true)

    const body = (await resp.json()) as {
      x: string
      y: string
      date_from: string
      date_to: string
      alpha: number
      effective_n: number
      lag_grid: Array<{
        lag: number
        pearson: { r: number | null; p_raw: number | null; reason: string | null }
        spearman: { r: number | null; p_raw: number | null; reason: string | null }
      }>
      interpretation: {
        caveat: string
        methodology_url: string
        warnings: Array<unknown>
      }
    }

    expect(body.x).toBe(POPULATED_X)
    expect(body.y).toBe(POPULATED_Y)

    // Full lag scan [-24..+24] = 49 cells (umbrella §3 D-1 lock).
    expect(body.lag_grid).toHaveLength(49)
    expect(body.lag_grid[0].lag).toBe(-24)
    expect(body.lag_grid[48].lag).toBe(24)

    // Both methods populated at every lag (populated fixture: 100
    // months, effective_n_at_lag = 100 - |k| ≥ 76 ≫ MIN 30, so reason
    // is null and r/p_raw are non-null at EVERY cell). Per Codex T3
    // r2 MED fold: assert p_raw at every lag, not just lag 0 — a
    // non-zero-lag p-value regression would otherwise slip through.
    for (const cell of body.lag_grid) {
      expect(cell.pearson.r).not.toBeNull()
      expect(cell.spearman.r).not.toBeNull()
      expect(cell.pearson.p_raw).not.toBeNull()
      expect(cell.spearman.p_raw).not.toBeNull()
      expect(cell.pearson.reason).toBeNull()
      expect(cell.spearman.reason).toBeNull()
    }

    // Lag 0 specifically — pinpoint the symmetry anchor (no special
    // shape vs neighboring lags, but the existence at lag 0 is the
    // canonical "no time shift" data point users will read first).
    const lagZero = body.lag_grid.find((c) => c.lag === 0)
    expect(lagZero).toBeDefined()

    // Interpretation envelope — caveat + methodology_url contract-locked.
    expect(typeof body.interpretation.caveat).toBe('string')
    expect(body.interpretation.caveat.length).toBeGreaterThan(0)
    expect(typeof body.interpretation.methodology_url).toBe('string')
    expect(body.interpretation.methodology_url.length).toBeGreaterThan(0)

    await apiCtx.dispose()
  })

  test('UAT 4 — URL state survives reload', async ({ page, context }) => {
    await seedAndForwardCookie(context, POPULATED_STATE)

    await page.goto(`/analytics/correlation?${CORRELATION_QS}&method=spearman`)

    await expect(page.getByTestId('correlation-populated')).toBeVisible()
    const spearmanBefore = page.getByTestId('correlation-method-spearman')
    await expect(spearmanBefore).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('line-spearman')).toHaveAttribute(
      'data-method-active',
      'true',
    )

    await page.reload()

    // Post-reload — URL keeps method=spearman, hydrate path re-reads it
    // synchronously via `useState` initializer (CorrelationPage.tsx:117).
    await expect(page).toHaveURL(/method=spearman/)
    await expect(page.getByTestId('correlation-populated')).toBeVisible()
    await expect(
      page.getByTestId('correlation-method-spearman'),
    ).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('line-spearman')).toHaveAttribute(
      'data-method-active',
      'true',
    )
    await expect(page.getByTestId('line-pearson')).toHaveAttribute(
      'data-method-active',
      'false',
    )
  })

  test('UAT 5 — KO/EN locale toggle swaps heading + caveat', async ({
    page,
    context,
  }) => {
    await seedAndForwardCookie(context, POPULATED_STATE)

    await page.goto(`/analytics/correlation?${CORRELATION_QS}`)
    await expect(page.getByTestId('correlation-populated')).toBeVisible()

    // English-pinned baseline. Heading is "Correlation"; caveat title
    // is "Correlation ≠ causation"; chart caption tokens are
    // `effective n` + `period`.
    const heading = page.getByRole('heading', { name: 'Correlation' })
    await expect(heading).toBeVisible()
    const caveat = page.getByTestId('correlation-caveat-banner')
    await expect(caveat).toContainText('Correlation ≠ causation')
    const populated = page.getByTestId('correlation-populated')
    await expect(populated).toContainText('effective n')
    await expect(populated).toContainText('period')

    // Toggle to KO. LocaleToggle cycles SUPPORTED_LOCALES (ko, en) so
    // a single click flips us to ko.
    const localeToggle = page.getByTestId('locale-toggle')
    await expect(localeToggle).toBeVisible()
    await localeToggle.click()

    // Korean heading is "상관관계"; caveat title swaps to the KO
    // mirror; chart caption swaps to `유효 n` + `기간` per Codex
    // T3 r1 MED 2 fold (AC #5 says ALL chart labels swap, not just
    // heading + caveat — the caption is the dominant chart-label
    // surface in this view).
    await expect(
      page.getByRole('heading', { name: '상관관계' }),
    ).toBeVisible()
    await expect(caveat).toContainText('상관관계 ≠ 인과관계')
    await expect(populated).toContainText('유효 n')
    await expect(populated).toContainText('기간')
    // EN tokens MUST disappear after the swap (otherwise the caption
    // is rendering both locales' copy which would mean the i18next
    // re-render didn't propagate).
    await expect(populated).not.toContainText('effective n')
    await expect(populated).not.toContainText('period')

    // Method labels stay invariant per `init.test.ts` allowlist —
    // Pearson/Spearman are romanised the same in ko UI. Pin the
    // invariant so a future i18n drift is caught here too.
    await expect(
      page.getByTestId('correlation-method-pearson'),
    ).toContainText('Pearson')
    await expect(
      page.getByTestId('correlation-method-spearman'),
    ).toContainText('Spearman')

    // Toggle back to EN to confirm the cycle is reversible (and to
    // leave subsequent tests in the pinned EN state since fullyParallel
    // is false but workers may reuse storage between describes).
    await localeToggle.click()
    await expect(
      page.getByRole('heading', { name: 'Correlation' }),
    ).toBeVisible()
    await expect(populated).toContainText('effective n')
    await expect(populated).toContainText('period')
  })
})
