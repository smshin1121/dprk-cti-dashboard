/**
 * RankedRowWithShareBar — presentational row used by the 4 dashboard
 * ranked panels (LocationsRanked / SectorBreakdown / ContributorsList
 * / GroupsMiniList) per DESIGN.md `## Dashboard Workspace Pattern >
 * ### Center-Pane Widget Surfaces > ranked-row-with-share-bar`.
 *
 * Anatomy:
 *   - 32×32 square avatar (canvas bg, body initials, 1px hairline
 *     border, sharp corners — Ferrari signature, NEVER rounded-full)
 *   - name (body sm)
 *   - optional sub-line (caption, muted)
 *   - horizontal share-bar (4px height, ink-muted fill at 100% width
 *     for top item, scaled by relative share for lower rows)
 *   - value (tabular-nums for column alignment)
 *   - optional percentage (caption, muted)
 *
 * Color discipline (G5 + Iteration Guide #5):
 *   - Bar fill is ink-muted only — NEVER `bg-signal` / `bg-primary` /
 *     chart palette. Bar is structure, not signal.
 *   - No hover state. Ferrari rejects hover backgrounds.
 *   - Hairline divider between rows; no shadows.
 *
 * Consumers compute `shareBarPct` themselves (head row = 100, lower
 * rows = count / max_count * 100). The component clamps to [0, 100]
 * defensively so a stale ratio never produces a >100% fill or a
 * negative width.
 *
 * Layer rule (L1): file lives in `apps/frontend/src/layout/`. No
 * `features/dashboard/*` import; consumed by the 4 ranked panel files
 * during T9 GREEN.
 */

interface RankedRowWithShareBarProps {
  /** Avatar copy — ISO2, initials, etc. Two characters works best. */
  readonly avatarText: string
  /** Primary row label. Truncates if it overflows the column. */
  readonly name: string
  /** Optional secondary line. Caption-sized, muted. */
  readonly sub?: string
  /** Tabular-nums value (count / score / etc.) — string for i18n. */
  readonly value: string
  /** Share-bar fill percent, [0, 100]. Out-of-range values are clamped. */
  readonly shareBarPct: number
  /** Optional percentage caption — pre-formatted (e.g. "33%"). */
  readonly pct?: string
  /**
   * Optional override for the bar-fill `data-testid`. When set, the
   * default `ranked-row-bar-fill` testid is replaced with this string.
   * Panel consumers (LocationsRanked / SectorBreakdown / etc.) pass
   * their per-row testid (e.g. `locations-ranked-bar-KR`) so existing
   * panel tests can target a specific row's bar fill without losing
   * the shared component contract. T2 RED isolated-component tests
   * never pass this prop and continue to assert against the default.
   */
  readonly barFillTestId?: string
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(Math.max(n, lo), hi)
}

export function RankedRowWithShareBar({
  avatarText,
  name,
  sub,
  value,
  shareBarPct,
  pct,
  barFillTestId,
}: RankedRowWithShareBarProps): JSX.Element {
  const widthPct = clamp(shareBarPct, 0, 100)

  return (
    <div
      data-testid="ranked-row"
      className="flex items-start gap-3 border-b border-border-card py-2"
    >
      <span
        data-testid="ranked-row-avatar"
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-none border border-border-card bg-app text-xs font-medium text-ink-muted"
      >
        {avatarText}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex items-baseline justify-between gap-3">
          <span
            data-testid="ranked-row-name"
            className="truncate text-sm text-ink"
          >
            {name}
          </span>
          <span className="flex shrink-0 items-baseline gap-2">
            <span
              data-testid="ranked-row-value"
              className="text-sm tabular-nums text-ink"
            >
              {value}
            </span>
            {pct !== undefined ? (
              <span
                data-testid="ranked-row-pct"
                className="text-xs text-ink-subtle"
              >
                {pct}
              </span>
            ) : null}
          </span>
        </div>
        {sub !== undefined ? (
          <span
            data-testid="ranked-row-sub"
            className="truncate text-xs text-ink-subtle"
          >
            {sub}
          </span>
        ) : null}
        <div
          data-testid="ranked-row-bar-track"
          className="h-1 w-full overflow-hidden rounded-none bg-app"
        >
          <div
            data-testid={barFillTestId ?? 'ranked-row-bar-fill'}
            role="presentation"
            aria-hidden
            className="h-full bg-ink-muted"
            style={{ width: `${widthPct}%` }}
          />
        </div>
      </div>
    </div>
  )
}
