/**
 * Detail-route path-param parsing (PR #14 Group E).
 *
 * The detail routes (`/reports/:id` / `/incidents/:id` / `/actors/:id`)
 * all accept a positive integer id. This helper centralizes the
 * malformed-input handling so each page uses the same guard:
 *
 *   const id = parseDetailId(useParams<{ id: string }>().id)
 *   if (id == null) return <NotFoundPanel ... />
 *
 * Returns `null` for:
 *   - absent / undefined / empty param
 *   - non-numeric strings (e.g. `/reports/abc`)
 *   - zero, negative, or non-integer values (`/reports/-1`, `/reports/1.5`)
 *   - decimal-y strings that `parseInt` truncates (e.g. `/reports/1.9`
 *     → 1 IS returned; that's desired — integer prefix of a malformed
 *     URL is still a valid lookup)
 *
 * The guard mirrors the hook-layer `enabled: Number.isInteger(id) &&
 * id > 0` condition exactly — same invariant on both sides means the
 * page renders the NotFound panel without firing an impossible-to-
 * satisfy fetch.
 */
export function parseDetailId(param: string | undefined): number | null {
  if (!param) return null
  const n = Number.parseInt(param, 10)
  return Number.isInteger(n) && n > 0 ? n : null
}
