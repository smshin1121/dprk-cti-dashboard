/**
 * React Query key factory. Centralizing key construction means:
 *
 * - Rename a key in ONE place when the BE route renames
 * - Easy grep — `queryKeys.me()` surfaces every consumer
 * - Stable keys: identical filter input → structurally equal key so
 *   React Query's shallow cache lookup hits the same entry
 *
 * Future groups append to this file:
 * - Group F: `actors(pagination)`, `reports(filters, cursor)`, etc.
 *
 * D5 lock — cache-key TLP isolation:
 * `dashboardSummary(filters)` takes `DashboardSummaryFilters` whose
 * type carries no tlp field. Toggling TLP in the UI MUST NOT
 * invalidate the dashboard cache; the single way to satisfy that is
 * to never put TLP in the key in the first place. Enforced at the
 * type boundary + pinned by `queryKeys.test.ts`.
 */

import type {
  AnalyticsFilters,
  AttackMatrixOptions,
  IncidentsTrendGroupBy,
} from './analyticsFilters'
import type { DashboardSummaryFilters } from './dashboardFilters'
import type {
  ActorListPagination,
  ActorReportsFilters,
  IncidentListFilters,
  ReportListFilters,
  SearchFilters,
} from './listFilters'

export const queryKeys = {
  me: () => ['me'] as const,
  dashboardSummary: (filters: DashboardSummaryFilters) =>
    ['dashboard', 'summary', filters] as const,

  /**
   * `/api/v1/actors` — pagination-only. No FilterBar input reaches
   * this key: the `ActorListPagination` type has no filter fields.
   */
  actors: (pagination: ActorListPagination) =>
    ['actors', pagination] as const,

  /**
   * `/api/v1/reports` + `/api/v1/incidents` — date-range filters +
   * cursor. `ReportListFilters` / `IncidentListFilters` have no
   * group/tlp fields, so TLP + group changes can NEVER invalidate
   * these caches. Pinned in `listFilters.test.ts`.
   */
  reports: (
    filters: ReportListFilters,
    pagination: { cursor?: string; limit?: number } = {},
  ) => ['reports', filters, pagination] as const,

  incidents: (
    filters: IncidentListFilters,
    pagination: { cursor?: string; limit?: number } = {},
  ) => ['incidents', filters, pagination] as const,

  /**
   * `/api/v1/analytics/*` — plan D2 + D9 (PR #13). Same D5 TLP-
   * isolation invariant as `dashboardSummary`: `AnalyticsFilters`
   * carries no tlp field, so a TLP toggle can NEVER invalidate these
   * caches. Per-endpoint keys keep fetch errors local (one failing
   * viz degrades one panel, not the whole dashboard).
   */
  analyticsAttackMatrix: (
    filters: AnalyticsFilters,
    options: AttackMatrixOptions = {},
  ) => ['analytics', 'attack_matrix', filters, options] as const,

  analyticsTrend: (filters: AnalyticsFilters) =>
    ['analytics', 'trend', filters] as const,

  /**
   * `/api/v1/analytics/incidents_trend` — PR #23 §6.A C1. Key carries
   * `groupBy` so the motivation and sector axes occupy different cache
   * slots even under identical date/group filters; the two stacked-
   * area widgets (PR #23 §6.C C7/C8) MUST NOT share a cache entry.
   */
  analyticsIncidentsTrend: (
    filters: AnalyticsFilters,
    groupBy: IncidentsTrendGroupBy,
  ) =>
    ['analytics', 'incidents_trend', groupBy, filters] as const,

  analyticsGeo: (filters: AnalyticsFilters) =>
    ['analytics', 'geo', filters] as const,

  /**
   * `/api/v1/reports/{id}` / `/incidents/{id}` / `/actors/{id}` —
   * plan D1 + D11 (PR #14 Group D). Detail pages aren't filterable:
   * the path-param id IS the identifier. Each key carries ONLY the
   * id — no FilterBar date / group / tlp state reaches these caches
   * because the hooks (`useReportDetail` / `useIncidentDetail` /
   * `useActorDetail`) don't subscribe to `useFilterStore`. Pinned
   * by `use{Report,Incident,Actor}Detail.test.tsx` no-refetch-on-
   * filter-toggle cases.
   */
  reportDetail: (id: number) => ['reports', 'detail', id] as const,
  incidentDetail: (id: number) => ['incidents', 'detail', id] as const,
  actorDetail: (id: number) => ['actors', 'detail', id] as const,

  /**
   * `/api/v1/reports/{id}/similar` — plan D8 (PR #14 Group D). Key
   * scope is `(report_id, k)` matching the BE Redis cache key
   * `similar_reports:{id}:{k}` exactly: changing the source report
   * or k opens a new cache slot on both sides. Mirrors the
   * `analyticsAttackMatrix` top_n pattern (caller-configurable arg,
   * not global filter). No filter state participates.
   */
  similarReports: (reportId: number, k: number) =>
    ['reports', reportId, 'similar', k] as const,

  /**
   * `/api/v1/actors/{id}/reports` — PR #15 Phase 3 slice 2 Group D
   * (plan D2 + D13). Key scope is `(actorId, filters, pagination)`
   * where `filters` = `{date_from?, date_to?}` and `pagination` =
   * `{cursor?, limit?}`. NO TLP, NO groupIds, NO q/tag/source —
   * `ActorReportsFilters` type has no such fields by construction,
   * so a future FilterBar toggle on TLP / group selection CANNOT
   * invalidate this cache. Pinned by `queryKeys.test.ts`.
   */
  actorReports: (
    actorId: number,
    filters: ActorReportsFilters,
    pagination: { cursor?: string; limit?: number } = {},
  ) => ['actors', actorId, 'reports', filters, pagination] as const,

  /**
   * `/api/v1/search` — PR #17 Phase 3 slice 3 Group D (plan D8 + D13).
   * Key scope is `(q, filters)` where `filters` =
   * `{date_from?, date_to?, limit?}`. The `q` string is passed
   * debounced by the hook layer (250ms) so identical post-debounce
   * values share a cache slot; the `filters` object carries only the
   * three whitelisted keys so TLP / groupIds / tag / source toggles
   * can NEVER invalidate this cache. Pinned by `queryKeys.test.ts`.
   */
  searchHits: (q: string, filters: SearchFilters) =>
    ['search', q, filters] as const,
} as const
