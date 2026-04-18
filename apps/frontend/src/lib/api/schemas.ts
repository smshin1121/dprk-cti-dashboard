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
