import '@testing-library/jest-dom/vitest'

import { afterEach, vi } from 'vitest'

// Minimal runtime config — mirrors what `config.ts` reads from
// `window.__APP_CONFIG__` at runtime. Tests that hit the api client
// would otherwise compose a literal "undefined" into the URL.
//
// Using a recognizable host means any accidental real fetch in a test
// fails with a DNS / connection error instead of silently hitting a
// cached localhost service.
;(window as unknown as { __APP_CONFIG__: Record<string, string> }).__APP_CONFIG__ = {
  apiUrl: 'http://api.test.invalid',
  llmProxyUrl: 'http://llm.test.invalid',
  appEnv: 'dev',
}

// Reset mocked fetch between tests so one test's mock can't bleed
// into the next. Individual tests still spy/restore as needed.
afterEach(() => {
  vi.restoreAllMocks()
})
