/**
 * World Map viz — design doc §4.2 area [C], plan D1 + D7 (PR #13
 * Group G).
 *
 * Data: `useGeo()` hook (PR #13 Group C, plan D2 shape `{countries:
 * [{iso2, count}]}`). The hook subscribes only to `dateFrom` /
 * `dateTo` / `groupIds` — TLP changes do not refetch.
 *
 * Projection: Natural Earth-style Mercator via `@visx/geo`, feeding
 * from the bundled Natural Earth 110m TopoJSON at
 * `src/assets/topojson/world-110m.json` (plan D7: no CDN; the file
 * ships with the Vite bundle).
 *
 * DPRK highlight (plan D7 lock):
 *   KP's highlight is GEOGRAPHIC — identity-driven. The country
 *   feature is identified by its ISO numeric id (`408`) in the
 *   TopoJSON. A distinct stroke + highlighted data attribute is
 *   applied to that feature REGARDLESS of whether the BE returned
 *   a KP row. The BE still returns KP as a plain country row (plan
 *   D2 + Group A implementation); that row's count colors the KP
 *   fill just like any other country. Highlight vs. count are
 *   orthogonal concerns.
 *
 * Render states (4, matching PR #12 KPICard pattern):
 *   - loading  — skeleton placeholder
 *   - error    — inline card + retry button (useGeo().refetch())
 *   - empty    — map still renders (gray fills) + centered empty-
 *                state overlay. Plan D8 empty-state UX carried over.
 *   - populated — color-coded country fills + tooltip on hover via
 *                 <title> element
 *
 * Isolation carried from PR #13 Groups C–F:
 *   - No TLP subscription (through useGeo's primitive selectors)
 *   - No locale leak into queryKey (Group F isolation test pins)
 *   - Tooltip text uses ISO2 + count from BE — no label-layer
 *     translation of country codes (plan D5 excludes BE domain
 *     values from i18n scope)
 */

import { Mercator } from '@visx/geo'
import { feature } from 'topojson-client'
import type { GeometryCollection, Topology } from 'topojson-specification'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import worldTopology from '../../assets/topojson/world-110m.json'
import { DPRK_ISO2, DPRK_NUMERIC_ID, numericToIso2 } from '../../lib/countryCodes'
import { cn } from '../../lib/utils'
import { useGeo } from '../analytics/useGeo'

// Feature-collection derivation runs once at module load — the
// TopoJSON is static so the conversion's result is cache-friendly.
const _topology = worldTopology as unknown as Topology<{
  countries: GeometryCollection
}>
const COUNTRY_FEATURES = feature(_topology, _topology.objects.countries).features

// Canvas dimensions — viewBox lets the SVG scale to container width
// while preserving aspect ratio.
const VIEW_WIDTH = 960
const VIEW_HEIGHT = 500

// Fills — Ferrari sequential ramp from canvas-elevated (no-data) to
// Tol cyan (high-count). Cyan is the dark-canvas-reordered slot 0
// from _palette.ts — its 11.4:1 contrast against bg-app keeps
// high-count countries legible. Rosso Corsa is reserved for DPRK
// highlight and AttackHeatmap top intensity per plan §0.1
// invariant 3.
const NO_DATA_FILL = '#3a3a3a' // slightly lifted canvas-elevated
const HIGH_COUNT_FILL = '#88CCEE' // Tol Muted cyan (dark-canvas slot 0)

function countFill(count: number, maxCount: number): string {
  if (maxCount <= 0 || count <= 0) return NO_DATA_FILL
  // Linear interpolation in sRGB between NO_DATA_FILL (#3a3a3a) and
  // HIGH_COUNT_FILL (#88CCEE). Single ramp keeps the sequential
  // story coherent without pulling in d3-scale-chromatic.
  const t = Math.min(1, count / maxCount)
  const r = Math.round(0x3a + (0x88 - 0x3a) * t)
  const g = Math.round(0x3a + (0xcc - 0x3a) * t)
  const b = Math.round(0x3a + (0xee - 0x3a) * t)
  return `rgb(${r} ${g} ${b})`
}

function featureNumericId(f: (typeof COUNTRY_FEATURES)[number]): string {
  // world-atlas features have `id` as string-numeric (e.g. "408")
  // but TopoJSON spec allows number too — coerce defensively.
  return String(f.id ?? '')
}

export function WorldMap(): JSX.Element {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch } = useGeo()

  const countMap = useMemo(() => {
    const m = new Map<string, number>()
    if (data) {
      for (const c of data.countries) m.set(c.iso2, c.count)
    }
    return m
  }, [data])

  const maxCount = useMemo(() => {
    if (!data || data.countries.length === 0) return 0
    return Math.max(...data.countries.map((c) => c.count))
  }, [data])

  if (isLoading) {
    return (
      <div
        data-testid="world-map-loading"
        role="status"
        aria-label={t('list.loading')}
        className="h-96 animate-pulse rounded-none border border-border-card bg-surface"
      />
    )
  }

  if (isError) {
    return (
      <div
        data-testid="world-map-error"
        role="alert"
        className="flex h-96 flex-col items-center justify-center gap-3 rounded-none border border-border-card bg-surface p-6"
      >
        <p className="text-sm text-ink-muted">{t('dashboard.error')}</p>
        <button
          type="button"
          data-testid="world-map-retry"
          onClick={() => {
            void refetch()
          }}
          className={cn(
            'rounded-none border border-border-card bg-app px-3 py-1.5 text-xs font-cta uppercase tracking-cta text-ink',
            'hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-ring',
          )}
        >
          {t('list.retry')}
        </button>
      </div>
    )
  }

  const isEmpty = !data || data.countries.length === 0

  return (
    <div
      data-testid="world-map"
      className="relative rounded-none border border-border-card bg-surface p-2"
    >
      <svg
        role="img"
        aria-label="World map of incident country counts"
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        className="block w-full"
      >
        <Mercator<(typeof COUNTRY_FEATURES)[number]>
          data={COUNTRY_FEATURES}
          scale={140}
          translate={[VIEW_WIDTH / 2, VIEW_HEIGHT / 2 + 60]}
        >
          {(mercator) => (
            <g data-testid="world-map-features">
              {mercator.features.map(({ feature: f, path }, index) => {
                const numericId = featureNumericId(f)
                const iso2 = numericToIso2(numericId) ?? ''
                const count = iso2 !== '' ? countMap.get(iso2) ?? 0 : 0
                const isDprk =
                  numericId === DPRK_NUMERIC_ID || iso2 === DPRK_ISO2
                const fill = countFill(count, maxCount)
                // Some 110m features lack an ISO numeric id (disputed
                // territories, etc). Fall back to array index for the
                // React key to stay unique.
                const key = numericId !== '' ? `n-${numericId}` : `i-${index}`

                return (
                  <path
                    key={key}
                    d={path ?? ''}
                    data-testid={`world-map-country-${numericId || `idx-${index}`}`}
                    data-iso2={iso2}
                    data-dprk={isDprk ? 'true' : undefined}
                    data-count={count}
                    fill={fill}
                    stroke={isDprk ? '#da291c' : '#5a5a5a'}
                    strokeWidth={isDprk ? 1.5 : 0.4}
                  >
                    <title>{`${iso2 || numericId}: ${count}`}</title>
                  </path>
                )
              })}
              {/* Centroid marker for DPRK — reinforces the highlight
                  when DPRK's geometry is tiny at 110m resolution. */}
              {mercator.features
                .filter(({ feature: f }) => featureNumericId(f) === DPRK_NUMERIC_ID)
                .map(({ centroid }) => (
                  <circle
                    key="dprk-marker"
                    data-testid="world-map-dprk-marker"
                    cx={centroid[0]}
                    cy={centroid[1]}
                    r={4}
                    fill="#da291c"
                    stroke="#ffffff"
                    strokeWidth={1}
                  />
                ))}
            </g>
          )}
        </Mercator>
      </svg>

      {isEmpty && (
        <div
          data-testid="world-map-empty"
          className="absolute inset-0 flex items-center justify-center bg-surface/70"
        >
          <p className="text-sm text-ink-muted">{t('dashboard.empty')}</p>
        </div>
      )}
    </div>
  )
}
