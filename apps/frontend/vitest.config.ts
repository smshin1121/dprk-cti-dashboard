import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  test: {
    // happy-dom over jsdom: jsdom ships its own AbortController /
    // AbortSignal implementation that fails Node's undici webidl
    // check when react-router 6.4+ creates a navigation Request.
    // happy-dom delegates to Node's native AbortController, so
    // react-router data-router navigation tests run cleanly.
    environment: 'happy-dom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    include: ['src/**/__tests__/**/*.test.{ts,tsx}'],
  },
})
