/**
 * Shell.tsx architectural guard — static-source assertion (PR 2 T5).
 *
 * Per `docs/plans/dashboard-workspace-retrofit.md` L1 + L10 + Codex F1
 * fold + memory `pattern_factory_wiring_guard`:
 *
 *   `Shell.tsx` MUST stay a generic frame (top-nav + FilterBar +
 *   <Outlet/>). It MUST NOT import any module under
 *   `apps/frontend/src/features/dashboard/`. The Dashboard Workspace
 *   Pattern's left/right rails are owned by `DashboardPage.tsx`, not
 *   by Shell.
 *
 * This test reads Shell.tsx as text and grep-style asserts the
 * import contract. Catches future contributor drift at test time
 * (CI fails before merge), not at code-review-only time.
 *
 * RED note: this test is GREEN at branch-creation time (Shell.tsx
 * already does not import features/dashboard/*). The test exists to
 * STAY green forever — i.e., it's a regression guard, not a TDD-RED
 * pin. Listed under T5 in the plan because the contract pin happens
 * here.
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const SHELL_PATH = resolve(__dirname, '..', 'Shell.tsx')

describe('Shell architectural guard', () => {
  it('Shell.tsx exists and is readable', () => {
    expect(() => readFileSync(SHELL_PATH, 'utf-8')).not.toThrow()
  })

  it('Shell.tsx does NOT import any features/dashboard/* module', () => {
    const source = readFileSync(SHELL_PATH, 'utf-8')
    // Match any import / re-export from a path containing
    // 'features/dashboard/'. Both forward-slash and backward-slash
    // path separators on Windows are covered.
    const featureDashboardImport =
      /from\s+['"][^'"]*features[/\\]dashboard[/\\]/g
    const matches = source.match(featureDashboardImport)
    expect(matches, `Shell.tsx must not import features/dashboard/*. Found: ${
      matches ? matches.join(', ') : 'none'
    }`).toBeNull()
  })

  it('Shell.tsx does NOT import DashboardLeftRail / DashboardRightRail / AlertsDrawer / AlertsRailSection (architectural lock L1)', () => {
    const source = readFileSync(SHELL_PATH, 'utf-8')
    // Symbol-level negative assertion — these names belong to the
    // Dashboard Workspace Pattern surfaces and must enter the tree
    // via DashboardPage, not Shell.
    expect(source).not.toMatch(/\bDashboardLeftRail\b/)
    expect(source).not.toMatch(/\bDashboardRightRail\b/)
    expect(source).not.toMatch(/\bAlertsDrawer\b/)
    expect(source).not.toMatch(/\bAlertsRailSection\b/)
  })

  it('Shell.tsx renders the canonical generic frame (header + FilterBar + main with Outlet)', () => {
    const source = readFileSync(SHELL_PATH, 'utf-8')
    // Sanity pin: Shell stays a frame. If a future change moves
    // Outlet or FilterBar out of Shell, this test forces a
    // conscious revisit of the L1 architectural lock.
    expect(source).toMatch(/<Outlet\b/)
    expect(source).toMatch(/<FilterBar\b/)
    expect(source).toMatch(/<header\b/)
    expect(source).toMatch(/<main\b/)
  })
})
