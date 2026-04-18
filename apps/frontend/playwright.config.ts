import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright config for the PR #12 shell E2E journey.
 *
 * Scope (plan D9 lock): ONE journey — login-seeded shell load →
 * /dashboard KPI render → navigate /actors table. Logout flow is
 * covered by Vitest integration, not E2E.
 *
 * Environment contract:
 *   E2E_BASE_URL              → FE served at, e.g., http://127.0.0.1:4173 (vite preview)
 *   E2E_API_BASE_URL          → BE served at, e.g., http://127.0.0.1:8000
 *
 * Both default to localhost defaults so local devs running
 * `docker compose up` can do `pnpm exec playwright test` without
 * any env plumbing.
 *
 * Session-cookie seeding:
 * The spec calls the BE's dev-only POST /_pact/provider_states
 * endpoint to seed fixtures + mint a signed session cookie (same
 * path used by the contract-verify job — drift-free). The returned
 * Set-Cookie is lifted into Playwright's browser context via
 * storageState. See `tests/e2e/login-dashboard-actors.spec.ts` for
 * the implementation.
 *
 * Artifacts:
 * Screenshots + videos + traces are retained on failure only so
 * the happy path doesn't pile up gigabytes in CI artifact storage.
 */
export default defineConfig({
  testDir: 'tests/e2e',
  // Generous timeout: full shell load exercises /auth/me, /dashboard/summary,
  // and /actors. On cold-start CI that can be 10+s.
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
