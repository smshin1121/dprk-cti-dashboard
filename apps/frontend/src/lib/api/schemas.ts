/**
 * Runtime Zod schemas for the endpoints the Shell actively consumes.
 *
 * Scope (plan D7 / D8 lock):
 * - `/api/v1/auth/me` — `currentUserSchema`
 * - `/api/v1/auth/logout` — 204, no response body schema
 * - `/api/v1/dashboard/summary` — added in Group E
 * - `/api/v1/actors` — added in Group F
 *
 * `/api/v1/reports` + `/api/v1/incidents` use types-only declarations
 * in their list routes — no runtime validation for PR #12 (plan D7
 * defers those to PR #13 when detail + advanced filter DTOs arrive).
 *
 * Source of truth: `contracts/openapi/openapi.json` (Group J snapshot
 * in PR #11). Schema drift between this file and the BE DTO surfaces
 * via the `currentUserSchema_parses_BE_example` contract test below
 * — when it fires, regenerate the BE snapshot, then update this file
 * to match. Codegen automation for this loop is plan D7-deferred.
 */

import { z } from 'zod'

/**
 * BE Pydantic model (`services/api/src/api/auth/schemas.py::CurrentUser`):
 * ```
 * sub: str
 * email: str
 * name: str | None = None
 * roles: list[str]
 * ```
 *
 * OpenAPI `required = ["sub", "email", "roles"]`. `name` allows
 * `{"type": ["string", "null"]}` (3.1 nullable via anyOf). `.nullish()`
 * on the Zod side accepts both `null` and missing — matching the BE
 * exactly, since Pydantic serializes `None` as JSON `null` and
 * `Optional[str]` allows the field to be absent on input.
 *
 * Why not `.nullable().optional()`: `.nullish()` is the idiomatic
 * shorthand and produces the same runtime parser — kept for
 * readability.
 */
export const currentUserSchema = z.object({
  sub: z.string().min(1),
  email: z.string(),
  name: z.string().nullish(),
  roles: z.array(z.string()),
})

export type CurrentUser = z.infer<typeof currentUserSchema>

/**
 * `/api/v1/dashboard/summary` — plan D6 shape. Mirrors BE Pydantic
 * `DashboardSummary` in `services/api/src/api/schemas/read.py`.
 * Field bounds (`ge=0`, `year in 1900..2100`) mirror the BE so the
 * FE refuses to ingest payloads the BE would not produce — cheap
 * canary for DB corruption or mock-server drift.
 *
 * BE wire shape (copy of the BE DTO):
 * ```
 * total_reports: int >= 0
 * total_incidents: int >= 0
 * total_actors: int >= 0
 * reports_by_year: [{ year: 1900..2100, count: int >= 0 }]
 * incidents_by_motivation: [{ motivation: str, count: int >= 0 }]
 * top_groups: [{ group_id: int, name: str, report_count: int >= 0 }]
 * ```
 */
export const dashboardYearCountSchema = z.object({
  year: z.number().int().gte(1900).lte(2100),
  count: z.number().int().gte(0),
})

export const dashboardMotivationCountSchema = z.object({
  motivation: z.string(),
  count: z.number().int().gte(0),
})

export const dashboardTopGroupSchema = z.object({
  group_id: z.number().int(),
  name: z.string(),
  report_count: z.number().int().gte(0),
})

export const dashboardSummarySchema = z.object({
  total_reports: z.number().int().gte(0),
  total_incidents: z.number().int().gte(0),
  total_actors: z.number().int().gte(0),
  reports_by_year: z.array(dashboardYearCountSchema),
  incidents_by_motivation: z.array(dashboardMotivationCountSchema),
  top_groups: z.array(dashboardTopGroupSchema),
})

export type DashboardYearCount = z.infer<typeof dashboardYearCountSchema>
export type DashboardMotivationCount = z.infer<typeof dashboardMotivationCountSchema>
export type DashboardTopGroup = z.infer<typeof dashboardTopGroupSchema>
export type DashboardSummary = z.infer<typeof dashboardSummarySchema>

/**
 * `/api/v1/actors` — plan D3 offset pagination + D7 Zod-validated.
 *
 * Mirrors BE `ActorItem` + `ActorListResponse` in
 * `services/api/src/api/schemas/read.py`. `aka` / `codenames` arrive
 * as arrays (N:M joins flattened on the BE). Most scalar fields are
 * optional because the BE model uses `| None = None` defaults — see
 * the Pydantic DTO for the source of truth.
 */
export const actorItemSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  mitre_intrusion_set_id: z.string().nullish(),
  aka: z.array(z.string()),
  description: z.string().nullish(),
  codenames: z.array(z.string()),
})

export const actorListResponseSchema = z.object({
  items: z.array(actorItemSchema),
  limit: z.number().int().gte(1).lte(200),
  offset: z.number().int().gte(0),
  total: z.number().int().gte(0),
})

export type ActorItem = z.infer<typeof actorItemSchema>
export type ActorListResponse = z.infer<typeof actorListResponseSchema>

/**
 * `/api/v1/reports` — plan D7 types-only (no runtime Zod).
 *
 * PR #12 shell-level only — no detail view, no advanced filter
 * surface. `/reports` + `/incidents` defer Zod to PR #13 when the
 * list DTOs grow detail-view fields; for now the FE trusts the BE
 * OpenAPI contract at the type layer. The cost of being wrong is a
 * rendering crash in the list table, not a silent data-integrity
 * failure, so types-only is an acceptable runtime risk in shell
 * scope.
 */
export interface ReportItem {
  id: number
  title: string
  url: string
  url_canonical: string
  published: string // ISO yyyy-mm-dd — BE `date` serializes as string
  source_id?: number | null
  source_name?: string | null
  lang?: string | null
  /**
   * TLP classification on the BE side. Present but NOT used by this
   * list table in PR #12 — D4 RLS filtering is deferred. When RLS
   * lands, the BE restricts which rows arrive here; the FE simply
   * renders what it gets.
   */
  tlp?: string | null
}

export interface ReportListResponse {
  items: ReportItem[]
  next_cursor: string | null
}

/**
 * `/api/v1/incidents` — plan D7 types-only.
 *
 * Incidents have the richest N:M surface (motivations × sectors ×
 * countries). Types-only keeps the list shell responsive without
 * committing to a runtime schema we'd edit every time a new field
 * lands in PR #13.
 */
export interface IncidentItem {
  id: number
  reported?: string | null
  title: string
  description?: string | null
  est_loss_usd?: number | null
  attribution_confidence?: string | null
  motivations: string[]
  sectors: string[]
  countries: string[]
}

export interface IncidentListResponse {
  items: IncidentItem[]
  next_cursor: string | null
}

/**
 * `/api/v1/analytics/*` — plan D2 lock, PR #13 Group A.
 *
 * Three read-only endpoints all share the same filter contract as
 * `/dashboard/summary` (date_from / date_to / group_id[]); attack_matrix
 * additionally accepts top_n (default 30, max 200). Responses are
 * parsed through Zod at the boundary so drift vs the BE Pydantic
 * models surfaces on ingest, not when a viz tries to render a
 * malformed shape.
 *
 * Shape mirrors `services/api/src/api/schemas/read.py::{Attack
 * MatrixResponse, TrendResponse, GeoResponse}` verbatim. The empty-
 * payload case (`{tactics: [], rows: []}` / `{buckets: []}` /
 * `{countries: []}`) parses successfully here — the FE viz owns the
 * empty-state card per plan D8, this layer just forwards the
 * BE-shaped payload through.
 */

export const tacticRefSchema = z.object({
  id: z.string(),
  name: z.string(),
})

export const attackTechniqueCountSchema = z.object({
  technique_id: z.string(),
  count: z.number().int().gte(0),
})

export const attackTacticRowSchema = z.object({
  tactic_id: z.string(),
  techniques: z.array(attackTechniqueCountSchema),
})

export const attackMatrixResponseSchema = z.object({
  tactics: z.array(tacticRefSchema),
  rows: z.array(attackTacticRowSchema),
})

export const trendBucketSchema = z.object({
  /** BE emits strict YYYY-MM (zero-padded); regex pins it to keep
   *  the viz's month-axis parsing unambiguous. */
  month: z.string().regex(/^\d{4}-\d{2}$/),
  count: z.number().int().gte(0),
})

export const trendResponseSchema = z.object({
  buckets: z.array(trendBucketSchema),
})

export const geoCountrySchema = z.object({
  /** ISO 3166-1 alpha-2. DPRK is `KP` — plan D7 lock says the FE
   *  highlights it; the BE treats it as a plain row here. */
  iso2: z.string().length(2),
  count: z.number().int().gte(0),
})

export const geoResponseSchema = z.object({
  countries: z.array(geoCountrySchema),
})

export type TacticRef = z.infer<typeof tacticRefSchema>
export type AttackTechniqueCount = z.infer<typeof attackTechniqueCountSchema>
export type AttackTacticRow = z.infer<typeof attackTacticRowSchema>
export type AttackMatrixResponse = z.infer<typeof attackMatrixResponseSchema>
export type TrendBucket = z.infer<typeof trendBucketSchema>
export type TrendResponse = z.infer<typeof trendResponseSchema>
export type GeoCountry = z.infer<typeof geoCountrySchema>
export type GeoResponse = z.infer<typeof geoResponseSchema>

/**
 * Detail views + similar reports — PR #14 Phase 3 slice 1 (Group D).
 *
 * Mirrors BE `services/api/src/api/schemas/read.py` for the three
 * detail endpoints + the /similar endpoint:
 *
 *   GET /api/v1/reports/{id}            → ReportDetail
 *   GET /api/v1/incidents/{id}          → IncidentDetail
 *   GET /api/v1/actors/{id}             → ActorDetail
 *   GET /api/v1/reports/{id}/similar    → SimilarReportsResponse
 *
 * Contract locks carried from `docs/plans/pr14-detail-views.md`:
 *
 * - **D9 payload caps** — `linked_incidents` ≤ 10,
 *   `linked_reports` ≤ 20, `similar.items` ≤ 50. BE applies the cap
 *   in SQL AND in the Pydantic DTO (`Field(max_length=...)`); this
 *   FE mirror puts the same ceiling on the Zod side so a BE bypass
 *   that oversized a response surfaces as a Zod parse error, not a
 *   silent UI overflow.
 *
 * - **D11 navigation contract** — report ↔ incident linking through
 *   `incident_sources` only. `actorDetailSchema` deliberately has
 *   NO `linked_reports` / `reports` / `recent_reports` key: that
 *   surface needs `report_codenames` and is out of scope this PR.
 *   Zod default strip-mode silently drops unknown keys, so a BE
 *   leak of such a field would be dropped before reaching the page.
 *   Pinned by `schemas.test.ts::actorDetailSchema_strips_reports_keys`.
 *
 * - **D10 empty-contract honesty** — `similarReportsResponseSchema`
 *   parses `{items: []}` successfully; the panel owns the empty
 *   state. No fake/heuristic fallback on either side.
 *
 * - **D8 similar semantics** — `score ∈ [0, 1]` (cosine similarity,
 *   emitted as `1 - distance`). `SIMILAR_K_*` constants mirror the
 *   BE router's `Query(ge=..., le=...)` bounds.
 */

/**
 * `LinkedIncidentSummary` — one row of `ReportDetail.linked_incidents`
 * (plan D9 + D11). Shallow summary only: a click navigates to
 * `/incidents/{id}` for the full detail.
 */
export const linkedIncidentSummarySchema = z.object({
  id: z.number().int(),
  title: z.string(),
  /** ISO YYYY-MM-DD; BE `date | None`. */
  reported: z.string().nullish(),
})

/**
 * `LinkedReportSummary` — one row of `IncidentDetail.linked_reports`
 * AND of `SimilarReportEntry.report` (plan D9 + D11). Shared shape
 * so the detail page + similar-panel render with one row component.
 * `published` is non-nullable on the BE (`date`), `source_name` is
 * nullable.
 */
export const linkedReportSummarySchema = z.object({
  id: z.number().int(),
  title: z.string(),
  url: z.string(),
  /** ISO YYYY-MM-DD; BE non-nullable `date`. */
  published: z.string(),
  source_name: z.string().nullish(),
})

/**
 * Similar-reports bounds (plan D8). Mirrors BE
 * `services/api/src/api/schemas/read.py::SIMILAR_K_*` — when the BE
 * bumps the cap, update here in the same PR. Not exported as a
 * `z.*` schema because the bound lives at the router query-param
 * layer; the DTO's `max_length=SIMILAR_K_MAX` is what this FE mirror
 * enforces via `.max()`.
 */
export const SIMILAR_K_MIN = 1
export const SIMILAR_K_MAX = 50
export const SIMILAR_K_DEFAULT = 10

/**
 * `GET /api/v1/reports/{id}` — plan D1 + D9 + D11.
 *
 * ReportItem-equivalent flat fields plus the detail-only free-form
 * fields (`summary` / `reliability` / `credibility`) plus flat
 * `tags` / `codenames` / `techniques` plus the capped
 * `linked_incidents` collection (D9 cap `REPORT_DETAIL_INCIDENTS_CAP`
 * = 10; ordered by `incidents.reported DESC, id DESC`).
 */
export const reportDetailSchema = z.object({
  id: z.number().int(),
  title: z.string(),
  url: z.string(),
  url_canonical: z.string(),
  published: z.string(),
  source_id: z.number().int().nullish(),
  source_name: z.string().nullish(),
  lang: z.string().nullish(),
  tlp: z.string().nullish(),
  summary: z.string().nullish(),
  reliability: z.string().nullish(),
  credibility: z.string().nullish(),
  tags: z.array(z.string()),
  codenames: z.array(z.string()),
  techniques: z.array(z.string()),
  linked_incidents: z.array(linkedIncidentSummarySchema).max(10),
})

/**
 * `GET /api/v1/incidents/{id}` — plan D1 + D9 + D11.
 *
 * IncidentItem-equivalent fields (including flat motivations /
 * sectors / countries arrays) plus the capped `linked_reports`
 * collection (D9 cap `INCIDENT_DETAIL_REPORTS_CAP` = 20; ordered by
 * `reports.published DESC, reports.id DESC`).
 */
export const incidentDetailSchema = z.object({
  id: z.number().int(),
  reported: z.string().nullish(),
  title: z.string(),
  description: z.string().nullish(),
  est_loss_usd: z.number().int().nullish(),
  attribution_confidence: z.string().nullish(),
  motivations: z.array(z.string()),
  sectors: z.array(z.string()),
  countries: z.array(z.string()),
  linked_reports: z.array(linkedReportSummarySchema).max(20),
})

/**
 * `GET /api/v1/actors/{id}` — plan D1 + D11.
 *
 * ActorItem-equivalent fields only. No `linked_reports` /
 * `reports` / `recent_reports` — that surface traverses
 * `report_codenames` and is D11 out-of-scope this PR. Zod strip-mode
 * makes the absence enforceable: a BE leak of any reports-like key
 * is silently dropped here, which `schemas.test.ts` pins.
 */
export const actorDetailSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  mitre_intrusion_set_id: z.string().nullish(),
  aka: z.array(z.string()),
  description: z.string().nullish(),
  codenames: z.array(z.string()),
})

/**
 * `SimilarReportEntry` — one kNN hit (plan D8).
 *
 * `score` is cosine similarity in `[0, 1]` (pgvector `<=>` is
 * distance; BE emits `1 - distance`). Higher is more similar.
 * Bound is inclusive per BE `Field(ge=0.0, le=1.0)`.
 */
export const similarReportEntrySchema = z.object({
  report: linkedReportSummarySchema,
  score: z.number().gte(0).lte(1),
})

/**
 * `GET /api/v1/reports/{id}/similar?k=N` — plan D2 + D8 + D10.
 *
 * `items` length bounded by `SIMILAR_K_MAX`. Empty arrays are legal
 * (D10: source has NULL embedding OR kNN returned zero rows → 200
 * with `{items: []}`). The panel renders an empty-state card; no
 * fake/heuristic fallback is injected here.
 */
export const similarReportsResponseSchema = z.object({
  items: z.array(similarReportEntrySchema).max(SIMILAR_K_MAX),
})

/**
 * `GET /api/v1/actors/{id}/reports` — plan D9 envelope reuse.
 *
 * PR #15 Phase 3 slice 2 Group D. Zod mirror of the BE
 * `ReportListResponse` envelope: `{items: ReportItem[], next_cursor:
 * string | null}` — NO `total`, NO `limit` echo (keyset envelope,
 * per plan D9). Runtime parse happens here; the existing types-only
 * `ReportItem` / `ReportListResponse` interfaces (kept from PR #12
 * for the `/reports` + `/incidents` list surfaces) stay untouched in
 * this PR.
 *
 * `actorReportsResponseSchema` is **reference-identical** to
 * `reportListResponseSchema` — the alias makes the call-site name
 * match the endpoint ("actor reports") while the single underlying
 * schema means a future widening of the envelope touches one place.
 * Pinned by `schemas.test.ts::actorReportsResponseSchema_equals_
 * reportListResponseSchema`.
 *
 * Empty-response contract (plan D8 / D15 b-c-d): `{items: [],
 * next_cursor: null}` parses successfully — no `.min(1)` guard, no
 * `eachLike`-style non-empty requirement. The consuming panel
 * renders an empty-state card; this layer forwards the BE shape
 * through verbatim.
 */
export const reportItemSchema = z.object({
  id: z.number().int(),
  title: z.string(),
  url: z.string(),
  url_canonical: z.string(),
  // BE `date` serializes as ISO-8601 string "YYYY-MM-DD".
  published: z.string(),
  source_id: z.number().int().nullish(),
  source_name: z.string().nullish(),
  lang: z.string().nullish(),
  tlp: z.string().nullish(),
})

export const reportListResponseSchema = z.object({
  items: z.array(reportItemSchema),
  next_cursor: z.string().nullable(),
})

/**
 * Alias — same schema reference as `reportListResponseSchema`. The
 * FE call site reads as `actorReportsResponseSchema` which keeps the
 * endpoint intent readable; the identity means there's no second
 * envelope to drift.
 */
export const actorReportsResponseSchema = reportListResponseSchema

/**
 * `GET /api/v1/search` — PR #17 Phase 3 slice 3 Group D (plan D9).
 *
 * FTS-only MVP this slice. Response envelope is
 * `{items: SearchHit[], total_hits, latency_ms}` and each hit carries
 * `{report: ReportItem, fts_rank, vector_rank}`. The `vector_rank`
 * slot is reserved forward-compat — literally `null` until the
 * follow-up hybrid PR fills it with a 1-indexed vector-kNN rank (see
 * memory `pattern_fts_first_hybrid_mvp`). The Zod type is
 * `z.number().int().nullable()` from day one so the follow-up ships
 * additively without a schema re-shape.
 *
 * Pinned against the BE OpenAPI example by
 * `schemas.test.ts::searchResponseSchema_parses_BE_examples`. Both
 * the populated and the D10 empty example must parse unchanged — a
 * schema tweak that flips either one surfaces at CI time before the
 * pact verifier runs.
 *
 * DO NOT alias this to `reportListResponseSchema` — `/search` hits
 * carry rank metadata (`fts_rank` / `vector_rank`) that list-style
 * responses do not, so the envelopes diverge at the item level.
 */
export const searchHitSchema = z.object({
  report: reportItemSchema,
  fts_rank: z.number(),
  vector_rank: z.number().int().nullable(),
})

export const searchResponseSchema = z.object({
  items: z.array(searchHitSchema),
  total_hits: z.number().int(),
  latency_ms: z.number().int(),
})

export type LinkedIncidentSummary = z.infer<typeof linkedIncidentSummarySchema>
export type LinkedReportSummary = z.infer<typeof linkedReportSummarySchema>
export type ReportDetail = z.infer<typeof reportDetailSchema>
export type IncidentDetail = z.infer<typeof incidentDetailSchema>
export type ActorDetail = z.infer<typeof actorDetailSchema>
export type SimilarReportEntry = z.infer<typeof similarReportEntrySchema>
export type SimilarReportsResponse = z.infer<typeof similarReportsResponseSchema>
export type SearchHit = z.infer<typeof searchHitSchema>
export type SearchResponse = z.infer<typeof searchResponseSchema>
