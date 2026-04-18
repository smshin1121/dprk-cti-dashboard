import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * Static wiring guard for apps/frontend/src/main.tsx.
 *
 * Background (review finding P1, 2026-04-18): Group A shipped
 * createQueryClient() with the 401 / retry / no-cascade-invalidate
 * contract, but main.tsx kept instantiating a bare `new QueryClient()`.
 * All unit tests used createQueryClient() directly and passed; the
 * runtime app silently bypassed the contract — stale identity on 401,
 * default 3-retry backoff masking transient errors, window-focus
 * refetch storms.
 *
 * This test reads main.tsx source and asserts the factory is wired
 * through. It's a static / source-level guard because:
 *   - main.tsx runs at module import time; spying on the Provider
 *     requires a heavier harness
 *   - the failure mode we're guarding against is purely textual
 *     (someone writes `new QueryClient()` by reflex), so a textual
 *     check is the correct fidelity
 *
 * If the wiring pattern changes (e.g. we add a separate
 * queryClientInstance.ts module), update this test's file target
 * rather than relaxing the assertions.
 */

const MAIN_TSX = resolve(__dirname, '..', 'main.tsx')
const source = readFileSync(MAIN_TSX, 'utf-8')

describe('main.tsx QueryClient wiring', () => {
  it('imports createQueryClient from lib/queryClient', () => {
    expect(source).toMatch(
      /import\s+\{[^}]*\bcreateQueryClient\b[^}]*\}\s+from\s+["']\.\/lib\/queryClient["']/,
    )
  })

  it('instantiates the client via createQueryClient()', () => {
    expect(source).toMatch(/createQueryClient\s*\(\s*\)/)
  })

  it('does NOT construct a bare `new QueryClient()` — bypasses the Group A contract', () => {
    expect(source).not.toMatch(/\bnew\s+QueryClient\s*\(/)
  })

  it('does NOT import QueryClient directly from @tanstack/react-query', () => {
    // QueryClientProvider import is fine; the CLASS is not.
    // Regex: the import specifiers block from '@tanstack/react-query'
    // must not contain a standalone `QueryClient` identifier (but may
    // contain `QueryClientProvider`).
    const match = source.match(
      /import\s+\{([^}]+)\}\s+from\s+["']@tanstack\/react-query["']/,
    )
    expect(match).not.toBeNull()
    const specifiers = match![1]
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
    expect(specifiers).not.toContain('QueryClient')
  })
})
