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
