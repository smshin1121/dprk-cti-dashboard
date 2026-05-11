import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * Static regression guard: apps/frontend/Dockerfile pins every base image
 * to `@sha256:<digest>`.
 *
 * Catches the silent-drift class where the deployment Dockerfile is
 * updated to a new base tag (e.g. node:23-alpine, nginx:1.28-alpine)
 * and the contributor forgets to capture a matching digest — producing
 * "works on my machine" supply-chain drift between local builds, CI
 * builds, and production rebuilds when the upstream tag moves.
 *
 * The test is intentionally lenient about EXACT image / tag / platform
 * syntax — it parses every line that starts with `FROM` and asserts the
 * target reference contains an `@sha256:` segment with 64 lowercase hex
 * characters. `FROM scratch` is explicitly allowed (scratch is a
 * pseudo-image with no content to pin).
 *
 * Refresh procedure when bumping tags (mirrored from the Dockerfile
 * header comments so contributors only need to read one place):
 *
 *   docker pull <image>:<new-tag>
 *   # capture the printed "Digest: sha256:..." line
 *   # replace the @sha256:... segment + bump the tag in lockstep
 *
 * Known limitation (acceptable trade-off): the digest regex accepts any
 * 64-hex value, so a contributor could in theory paste a syntactically
 * valid but content-wrong digest. Catching that would require pulling
 * the image at test time — a network round-trip we deliberately keep
 * out of the unit-test layer. CI's container build job is the second
 * line of defense (build fails on digest mismatch).
 *
 * Per `pattern_layer_boundary_lock_via_static_source` (PR #47 model):
 * mechanizes the "pin to @sha256:<digest> before production" TODO that
 * sat above each FROM since PR #1 (Phase 0). The frontend Dockerfile
 * is multi-stage (builder + runtime), so this test covers both FROMs.
 */

const DOCKERFILE_PATH = resolve(__dirname, '..', '..', 'Dockerfile')
const FROM_PATTERN = /^\s*FROM\s+(.+?)(?:\s+AS\s+\w+\s*)?$/gim
const DIGEST_PATTERN = /@sha256:[0-9a-f]{64}\b/

function fromTargets(dockerfileText: string): string[] {
  const targets: string[] = []
  for (const match of dockerfileText.matchAll(FROM_PATTERN)) {
    let raw = match[1].trim()
    // Defensive: drop trailing "AS <stage>" if the optional group missed it.
    raw = raw.replace(/\s+AS\s+\w+\s*$/i, '')
    // Drop leading "--platform=..." flag(s).
    raw = raw.replace(/^(?:--\S+\s+)+/, '')
    targets.push(raw)
  }
  return targets
}

describe('apps/frontend/Dockerfile digest pin', () => {
  it('Dockerfile exists at the expected path', () => {
    // Read once at suite scope to fail loud if the path math is wrong.
    expect(() => readFileSync(DOCKERFILE_PATH, 'utf-8')).not.toThrow()
  })

  it('has at least one FROM directive (digest assertion is vacuous otherwise)', () => {
    const text = readFileSync(DOCKERFILE_PATH, 'utf-8')
    const targets = fromTargets(text)
    expect(targets.length).toBeGreaterThan(0)
  })

  it('pins every FROM target to @sha256:<64-hex> (or scratch)', () => {
    const text = readFileSync(DOCKERFILE_PATH, 'utf-8')
    const targets = fromTargets(text)

    const unpinned = targets.filter((target) => {
      if (target.trim().toLowerCase() === 'scratch') return false
      if (DIGEST_PATTERN.test(target)) return false
      return true
    })

    expect(
      unpinned,
      `apps/frontend/Dockerfile has FROM directives without an @sha256:<digest> pin: ${JSON.stringify(unpinned)}. ` +
        `Run \`docker pull <image>:<tag>\` to capture the current digest and append it as \`@sha256:<digest>\` to the FROM line.`,
    ).toEqual([])
  })
})
