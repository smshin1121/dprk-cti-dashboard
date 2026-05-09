/**
 * Phase 3 Slice 3 D-1 — CorrelationPage (T9 base + T11 i18n keys).
 *
 * 4-state render orchestrator (Plan §B8 a):
 *   - `correlation-loading`   — primary fetch in flight
 *   - `correlation-error`     — primary fetch errored; `data-error-type`
 *                               carries the parsed
 *                               `error.detail.detail[0].type` for B10
 *                               typed-reason copy mapping
 *   - `correlation-empty`     — x or y not chosen yet (catalog loaded
 *                               but `useCorrelation` `enabled: false`)
 *   - `correlation-populated` — primary fetch resolved
 *
 * URL-state surface (Plan §B5, 5 keys: `x`, `y`, `date_from`,
 * `date_to`, `method`). Hydration runs synchronously on first render
 * via `useState` initializer so `useCorrelation` fires with the
 * correct args on the first frame — eliminates the "empty-then-real"
 * fetch-pair that a `useLayoutEffect` hydrate would produce, which
 * would inflate the cache test's primary-fetch count beyond 1.
 *
 * URL write-back fires `window.history.replaceState` directly, same
 * pattern as `useFilterUrlSync`. `MemoryRouter` reads from its in-
 * memory location, but write-back lands on `window.history` so the
 * tests' replaceState spy captures the writes. The first emit run is
 * skipped via `isInitialMountRef` so no spurious mount-time write
 * fires (`pitfall_browser_router_init_replaceState`); React Router
 * 6.4+ already fires its own `replaceState(undefined)` on mount, and
 * adding ours on top would produce two writes for the same URL.
 *
 * Re-hydrate on `location.search` change covers `popstate` (back /
 * forward), programmatic `useNavigate({ search })`, and any other
 * upstream URL mutation. The `useState` initializer alone only fires
 * once per mount, so without this effect a back-button press from a
 * later correlation query would leave page state, fetch args, and
 * the per-method markers stale even though the address bar updated.
 * The effect is keyed on `location.search` (router-tracked, not
 * `window.location.search`) so our own `replaceState` write-back
 * does not retrigger it (router does not listen to manual
 * `replaceState`). The shape comparison short-circuits identical
 * URLs so the very first run on mount is a no-op.
 *
 * Method toggle is purely visual (Plan §4 T4 lock — `method` is NOT
 * in the cache key). `useCorrelation` runs against
 * `(x, y, dateFrom, dateTo, alpha)` and the chart picks which of the
 * two pre-fetched series to highlight via the `method` prop. Pinned
 * by `pattern_shared_query_cache_multi_subscriber`.
 */

import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation } from 'react-router-dom'

import { ApiError } from '../../../lib/api'
import { CorrelationCaveatBanner } from './CorrelationCaveatBanner'
import { CorrelationFilters } from './CorrelationFilters'
import { CorrelationLagChart } from './CorrelationLagChart'
import { CorrelationWarningChips } from './CorrelationWarningChips'
import { useCorrelation } from './useCorrelation'
import { useCorrelationSeries } from './useCorrelationSeries'

const ALPHA = 0.05

type Method = 'pearson' | 'spearman'

interface CorrelationUrlState {
  x: string
  y: string
  dateFrom: string | null
  dateTo: string | null
  method: Method
}

function readMethod(raw: string | null): Method {
  return raw === 'spearman' ? 'spearman' : 'pearson'
}

function readUrlState(search: string): CorrelationUrlState {
  const params = new URLSearchParams(search)
  return {
    x: params.get('x') ?? '',
    y: params.get('y') ?? '',
    dateFrom: params.get('date_from') || null,
    dateTo: params.get('date_to') || null,
    method: readMethod(params.get('method')),
  }
}

function encodeUrlSearch(state: CorrelationUrlState): string {
  const params = new URLSearchParams()
  if (state.x) params.set('x', state.x)
  if (state.y) params.set('y', state.y)
  if (state.dateFrom) params.set('date_from', state.dateFrom)
  if (state.dateTo) params.set('date_to', state.dateTo)
  params.set('method', state.method)
  return params.toString()
}

function readErrorType(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null
  const detail = error.detail as { detail?: Array<{ type?: string }> } | null
  return detail?.detail?.[0]?.type ?? null
}

function urlStateEqual(a: CorrelationUrlState, b: CorrelationUrlState): boolean {
  return (
    a.x === b.x &&
    a.y === b.y &&
    a.dateFrom === b.dateFrom &&
    a.dateTo === b.dateTo &&
    a.method === b.method
  )
}

export function CorrelationPage(): JSX.Element {
  const { t } = useTranslation()
  const location = useLocation()
  const [state, setState] = useState<CorrelationUrlState>(() =>
    readUrlState(location.search),
  )

  // Re-hydrate when `location.search` changes from outside the page
  // (popstate / programmatic navigate). Identity-compares the
  // decoded URL against current state so the very first run on
  // mount is a no-op and our own write-back does not retrigger
  // setState (router does not listen to manual replaceState).
  useEffect(() => {
    const next = readUrlState(location.search)
    setState((prev) => (urlStateEqual(prev, next) ? prev : next))
  }, [location.search])

  const isInitialMountRef = useRef(true)
  useEffect(() => {
    if (isInitialMountRef.current) {
      isInitialMountRef.current = false
      return
    }
    if (typeof window === 'undefined') return
    const next = encodeUrlSearch(state)
    const current = window.location.search.replace(/^\?/, '')
    if (next === current) return
    const pathname = window.location.pathname
    const hash = window.location.hash
    window.history.replaceState(
      window.history.state,
      '',
      `${pathname}?${next}${hash}`,
    )
  }, [state])

  const catalogQuery = useCorrelationSeries()
  const correlationQuery = useCorrelation(
    state.x,
    state.y,
    state.dateFrom,
    state.dateTo,
    ALPHA,
  )

  const catalog = catalogQuery.data?.series ?? []

  const filters = (
    <CorrelationFilters
      catalog={catalog}
      x={state.x}
      y={state.y}
      dateFrom={state.dateFrom}
      dateTo={state.dateTo}
      onChangeX={(id) => setState((s) => ({ ...s, x: id }))}
      onChangeY={(id) => setState((s) => ({ ...s, y: id }))}
      onChangeDateFrom={(d) => setState((s) => ({ ...s, dateFrom: d }))}
      onChangeDateTo={(d) => setState((s) => ({ ...s, dateTo: d }))}
    />
  )

  const methodToggle = (
    <div role="group" aria-label={t('correlation.methodToggle.ariaLabel')} className="flex gap-2">
      <button
        type="button"
        data-testid="correlation-method-pearson"
        aria-pressed={state.method === 'pearson'}
        onClick={() => setState((s) => ({ ...s, method: 'pearson' }))}
        className={
          state.method === 'pearson'
            ? 'rounded-none border border-border-strong bg-surface px-3 py-1 text-xs font-cta uppercase tracking-cta text-ink'
            : 'rounded-none border border-border-card bg-app px-3 py-1 text-xs font-cta uppercase tracking-cta text-ink-muted hover:border-border-strong'
        }
      >
        {t('correlation.method.pearson')}
      </button>
      <button
        type="button"
        data-testid="correlation-method-spearman"
        aria-pressed={state.method === 'spearman'}
        onClick={() => setState((s) => ({ ...s, method: 'spearman' }))}
        className={
          state.method === 'spearman'
            ? 'rounded-none border border-border-strong bg-surface px-3 py-1 text-xs font-cta uppercase tracking-cta text-ink'
            : 'rounded-none border border-border-card bg-app px-3 py-1 text-xs font-cta uppercase tracking-cta text-ink-muted hover:border-border-strong'
        }
      >
        {t('correlation.method.spearman')}
      </button>
    </div>
  )

  let body: JSX.Element
  if (!state.x || !state.y) {
    body = (
      <div data-testid="correlation-empty" role="status" className="py-md text-sm text-ink-muted">
        {t('correlation.state.emptyPickXY')}
      </div>
    )
  } else if (correlationQuery.isError) {
    const errorType = readErrorType(correlationQuery.error)
    const errorCopy =
      errorType === 'value_error.insufficient_sample'
        ? t('correlation.state.errorInsufficientSample')
        : errorType === 'value_error.identical_series'
          ? t('correlation.state.errorIdenticalSeries')
          : t('correlation.state.errorUnknown')
    body = (
      <div
        data-testid="correlation-error"
        role="alert"
        data-error-type={errorType ?? 'unknown'}
        className="py-md text-sm text-ink"
      >
        {errorCopy}
      </div>
    )
  } else if (correlationQuery.isLoading) {
    body = (
      <div
        data-testid="correlation-loading"
        role="status"
        aria-busy="true"
        className="py-md text-sm text-ink-muted"
      >
        {t('correlation.state.loading')}
      </div>
    )
  } else if (correlationQuery.data) {
    body = (
      <div data-testid="correlation-populated" className="flex flex-col gap-md">
        <CorrelationLagChart data={correlationQuery.data} method={state.method} />
        <CorrelationWarningChips
          warnings={correlationQuery.data.interpretation.warnings}
        />
      </div>
    )
  } else {
    body = (
      <div data-testid="correlation-loading" role="status" aria-busy="true" className="py-md text-sm text-ink-muted">
        {t('correlation.state.loading')}
      </div>
    )
  }

  return (
    <section
      data-testid="correlation-page"
      data-page-class="analyst-workspace"
      aria-labelledby="correlation-heading"
      className="flex min-h-screen flex-col gap-md px-lg py-md"
    >
      {/* Per-method active markers — rendered at page level so they
          stay available across all 4 render branches (loading /
          error / empty / populated). The URL-hydrate test asserts
          `data-method-active` synchronously after the primary fetch
          fires but before React Query has flushed isSuccess, so the
          markers must NOT live inside the populated-only chart. */}
      <span
        hidden
        data-testid="line-pearson"
        data-method-active={state.method === 'pearson' ? 'true' : 'false'}
      />
      <span
        hidden
        data-testid="line-spearman"
        data-method-active={state.method === 'spearman' ? 'true' : 'false'}
      />
      <header className="flex h-md items-center justify-between gap-4">
        <h1 id="correlation-heading" className="text-xl font-semibold tracking-tight text-ink">
          {t('correlation.page.heading')}
        </h1>
        {methodToggle}
      </header>
      <CorrelationCaveatBanner />
      {filters}
      {body}
    </section>
  )
}
