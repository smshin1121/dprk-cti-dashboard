import { readdirSync, readFileSync, statSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import { URL_STATE_KEYS } from '../../../lib/urlState'

/**
 * Static scope-lock + URL-state invariance tests for PR #15 Group E
 * (plan D18 + OI4 carry).
 *
 * Plan D18 says `ActorLinkedReportsPanel` must mount ONLY on
 * `ActorDetailPage`. A plain runtime test (querying the DOM) cannot
 * prove absence of future cross-page imports; grepping the source
 * does. Pattern lifted from `src/__tests__/main-wiring.test.ts`
 * (the createQueryClient factory-wiring guard from PR #12 Group A).
 *
 * Plan does not widen URL-state keys — the existing 5-key whitelist
 * (date_from, date_to, group_id, view, tab) stays exactly as-is.
 * Adding an actor-reports cursor to the URL would be a scope
 * widening; D18 + D2 lock that to "no new URL state this slice". The
 * test below asserts the whitelist did not grow.
 *
 * If the panel later needs a broader consumer set (e.g. dashboard
 * reuse), update this test's expectation rather than relaxing the
 * import scan.
 */

const SRC_ROOT = resolve(__dirname, '..', '..', '..')

// Files that are EXPECTED to import ActorLinkedReportsPanel. Any
// other hit is a D18 violation.
const EXPECTED_IMPORTERS = new Set([
  resolve(SRC_ROOT, 'routes', 'ActorDetailPage.tsx'),
])

// Also allowed: the panel's own test files (they import the component
// under test). Computed dynamically to stay robust against renames.
const PANEL_DIR = resolve(SRC_ROOT, 'features', 'actor')
const PANEL_TEST_DIR = resolve(PANEL_DIR, '__tests__')

function walkSourceFiles(root: string): string[] {
  const out: string[] = []
  function walk(dir: string): void {
    for (const entry of readdirSync(dir)) {
      if (entry === 'node_modules' || entry === '__pycache__') continue
      const full = resolve(dir, entry)
      const s = statSync(full)
      if (s.isDirectory()) {
        walk(full)
      } else if (
        full.endsWith('.ts') ||
        full.endsWith('.tsx') ||
        full.endsWith('.js') ||
        full.endsWith('.jsx')
      ) {
        out.push(full)
      }
    }
  }
  walk(root)
  return out
}

const IMPORT_RX = /from\s+['"](?:[^'"]*\/)?ActorLinkedReportsPanel['"]/

describe('D18 scope lock — ActorLinkedReportsPanel consumers', () => {
  it('only ActorDetailPage imports the panel (no dashboard / list / shell reuse)', () => {
    const files = walkSourceFiles(SRC_ROOT)
    const importers: string[] = []

    for (const file of files) {
      // Skip the panel itself + its test suite — they import /
      // export the component by definition.
      if (file.startsWith(PANEL_DIR + '\\') || file.startsWith(PANEL_DIR + '/')) {
        continue
      }
      if (
        file.startsWith(PANEL_TEST_DIR + '\\') ||
        file.startsWith(PANEL_TEST_DIR + '/')
      ) {
        continue
      }
      const src = readFileSync(file, 'utf-8')
      if (IMPORT_RX.test(src)) {
        importers.push(file)
      }
    }

    const actualSet = new Set(importers)
    expect(actualSet).toEqual(EXPECTED_IMPORTERS)
  })
})

// Plan OI4 carry — PR #15 does NOT widen URL-state keys. The
// 5-key whitelist locked in PR #13 Group E stays identical.
describe('URL_STATE_KEYS invariance — PR #15 does not add URL state', () => {
  it('URL_STATE_KEYS remains the PR #13 locked 5-tuple', () => {
    expect([...URL_STATE_KEYS]).toEqual([
      'date_from',
      'date_to',
      'group_id',
      'view',
      'tab',
    ])
  })

  it('URL_STATE_KEYS does NOT include an actor / reports / cursor marker', () => {
    const joined = [...URL_STATE_KEYS].join(' ').toLowerCase()
    expect(joined).not.toContain('actor')
    expect(joined).not.toContain('cursor')
    expect(joined).not.toContain('limit')
    // The `report` substring must not mean "actor-reports cursor
    // key". `date_from` / `date_to` / etc. obviously pass this too.
    for (const k of URL_STATE_KEYS) {
      expect(k).not.toMatch(/actor|report|cursor/i)
    }
  })
})
