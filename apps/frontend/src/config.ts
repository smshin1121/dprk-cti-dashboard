/**
 * Runtime configuration pattern.
 *
 * `window.__APP_CONFIG__` is populated by `/config.js`, which is generated at
 * container startup by the nginx entrypoint script from environment variables.
 * During `vite dev`, no `/config.js` is served, so we fall back to
 * `import.meta.env.VITE_*` for developer ergonomics.
 */

export interface AppConfig {
  apiUrl: string
  llmProxyUrl: string
  appEnv: 'dev' | 'staging' | 'prod'
}

declare global {
  interface Window {
    __APP_CONFIG__?: Partial<AppConfig>
  }
}

function readRuntime(): Partial<AppConfig> {
  if (typeof window === 'undefined') return {}
  return window.__APP_CONFIG__ ?? {}
}

function readDevFallback(): Partial<AppConfig> {
  // import.meta.env is only populated during `vite dev` / `vite build`; in the
  // nginx-served production image, the bundle is compiled and these values are
  // whatever was present at build time (usually empty strings). Runtime values
  // take precedence.
  return {
    apiUrl: import.meta.env.VITE_API_URL,
    llmProxyUrl: import.meta.env.VITE_LLM_PROXY_URL,
    appEnv: (import.meta.env.VITE_APP_ENV as AppConfig['appEnv']) ?? 'dev',
  }
}

const runtime = readRuntime()
const dev = readDevFallback()

export const config: AppConfig = {
  apiUrl: runtime.apiUrl ?? dev.apiUrl ?? '/api/v1',
  llmProxyUrl: runtime.llmProxyUrl ?? dev.llmProxyUrl ?? '',
  appEnv: runtime.appEnv ?? dev.appEnv ?? 'dev',
}
