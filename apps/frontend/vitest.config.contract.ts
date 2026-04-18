import { defineConfig } from 'vitest/config'

// Separate vitest project for the pact-js consumer tests (plan
// risk-mitigation): pact-js spawns its own native FFI mock server
// per test, which is heavier than the unit-test loop. Isolating it
// keeps the regular `pnpm test` lean and lets CI run contract tests
// in a dedicated step that's allowed to be slower / install native
// binaries.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['tests/contract/**/*.pact.test.ts'],
    // pact-js v3 native mock server bind/teardown can take ~1-2s per
    // interaction on Windows; double the default 5s to be safe.
    testTimeout: 30_000,
    hookTimeout: 30_000,
    // Run sequentially so the same PactV3 instance accumulates
    // interactions deterministically into one pact file.
    fileParallelism: false,
    pool: 'forks',
    poolOptions: {
      forks: { singleFork: true },
    },
  },
})
