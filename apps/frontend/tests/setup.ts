import '@testing-library/jest-dom/vitest'

import { afterEach, vi } from 'vitest'

// ---------------------------------------------------------------------------
// AbortController compatibility shim for jsdom + react-router 6.4+ data APIs
// ---------------------------------------------------------------------------
//
// react-router 6.4+ (createMemoryRouter / createBrowserRouter) builds a
// `new Request(url, { signal })` inside `createClientSideRequest` on every
// navigation. Node's undici `Request` validates `signal` with a webidl
// check against Node's native `AbortSignal` prototype. jsdom ships its
// own `AbortController` / `AbortSignal` attached to the window object,
// whose prototype chain does NOT match Node's native class — so undici
// throws "Expected signal to be an instance of AbortSignal" and the
// navigation is aborted with an unhandled rejection.
//
// Fix: force both `globalThis` and `window` to use Node's native
// AbortController / AbortSignal classes, captured via the dynamic
// `import("node:util")` form below. This runs after jsdom's env init
// (setupFiles ordering) but before any test navigation fires, so all
// subsequent React Router + apiClient code paths see one consistent
// AbortController class.
//
// If we stop using jsdom (switching to happy-dom etc.) this block can
// come out.
// ---------------------------------------------------------------------------
{
  // Node exposes AbortController / AbortSignal as globals in >= 15.
  // We pull them off globalThis BEFORE jsdom has a chance to shadow
  // them by taking the reference here (module init order).
  const NodeAbortController = globalThis.AbortController
  const NodeAbortSignal = globalThis.AbortSignal
  if (typeof window !== 'undefined') {
    // Override jsdom's window-level versions so any code that reaches
    // through window (React Router does not, but defense in depth) also
    // sees the Node class.
    Object.defineProperty(window, 'AbortController', {
      value: NodeAbortController,
      configurable: true,
      writable: true,
    })
    Object.defineProperty(window, 'AbortSignal', {
      value: NodeAbortSignal,
      configurable: true,
      writable: true,
    })
  }
  // Re-assign globalThis references to be safe — some bundlers rebind
  // globals on module-scope access.
  Object.defineProperty(globalThis, 'AbortController', {
    value: NodeAbortController,
    configurable: true,
    writable: true,
  })
  Object.defineProperty(globalThis, 'AbortSignal', {
    value: NodeAbortSignal,
    configurable: true,
    writable: true,
  })
}

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
