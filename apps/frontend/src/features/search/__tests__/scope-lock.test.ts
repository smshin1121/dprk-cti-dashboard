import { readdirSync, readFileSync, statSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * Static scope-lock for PR #17 Group E (plan D18).
 *
 * `SearchResultsSection` is a palette-internal component — the only
 * legitimate consumer is `CommandPaletteButton`. A runtime test
 * (querying the DOM) cannot prove the absence of future cross-page
 * imports, but grepping the source tree at build time can.
 *
 * Pattern lifted verbatim from `src/features/actor/__tests__/
 * scope-lock.test.ts` (PR #15 Group E) so a reviewer scanning the
 * test tree sees the same shape applied to this slice.
 *
 * If a future slice legitimately needs the component elsewhere (e.g.
 * a dedicated search surface), update this test's expectation in
 * the SAME PR that widens the usage — do NOT relax the scan.
 */

const SRC_ROOT = resolve(__dirname, '..', '..', '..')

// Files that are EXPECTED to import SearchResultsSection. Any other
// hit is a D18 violation.
const EXPECTED_IMPORTERS = new Set([
  resolve(SRC_ROOT, 'components', 'CommandPaletteButton.tsx'),
])

// Also allowed: the component's own test files (they import it
// under test). Computed dynamically to stay robust against renames.
const SECTION_DIR = resolve(SRC_ROOT, 'features', 'search')
const SECTION_TEST_DIR = resolve(SECTION_DIR, '__tests__')

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

const IMPORT_RX = /from\s+['"](?:[^'"]*\/)?SearchResultsSection['"]/

describe('D18 scope lock — SearchResultsSection consumers', () => {
  it('only CommandPaletteButton imports the section (no dashboard / route / shell reuse)', () => {
    const files = walkSourceFiles(SRC_ROOT)
    const importers: string[] = []

    for (const file of files) {
      // Skip the section's own directory + its test suite — they
      // import / export the component by definition.
      if (
        file.startsWith(SECTION_DIR + '\\') ||
        file.startsWith(SECTION_DIR + '/')
      ) {
        continue
      }
      if (
        file.startsWith(SECTION_TEST_DIR + '\\') ||
        file.startsWith(SECTION_TEST_DIR + '/')
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
