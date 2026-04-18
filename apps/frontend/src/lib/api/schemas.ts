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
