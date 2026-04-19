"""Actors router — /api/v1/actors/...

Endpoints:
- ``GET /api/v1/actors`` — offset-paginated list (PR #11 Group B).
- ``GET /api/v1/actors/{actor_id}`` — single actor detail with
  codenames (PR #14 Phase 3 slice 1 Group A, plan D1 + D11).

Plan §2.3 matrix: offset pagination — plan D3 keeps actors off keyset
because the group count is small and sort-stable under inserts.
Default sort ``name ASC, id ASC`` per plan D11 lives in the
repository layer.

RBAC: all five roles (analyst / researcher / policy / soc / admin)
read these endpoints per plan "Inherited locks" and §9.3.

Filter surface for /actors (list): intentionally empty (plan D5).

Detail endpoint scope (PR #14 plan D11 lock):
- Returns core actor fields + codenames only.
- Does NOT traverse ``report_codenames`` to surface reports that
  mention this actor — that surface needs its own endpoint with a
  locked pagination + filter contract; carried to a later Phase 3
  slice. The FE actor detail page this PR has no "recent reports"
  panel.

Rate limit (plan D2 / Group H): ``60/minute`` per user bucket via
``session_or_ip_key`` — same-session cookie → same bucket, no
cookie → client-IP bucket. Scope is per-decorated-route (slowapi
semantics), so each actor endpoint's bucket is independent of the
/reports / /incidents / /dashboard buckets even for the same user.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import date

from ..auth.schemas import CurrentUser
from ..db import get_db
from ..deps import require_role
from ..rate_limit import get_limiter
from ..read import actor_reports, detail_aggregator, repositories as read_repositories
from ..read.pagination import CursorDecodeError, decode_cursor, encode_cursor
from ..schemas.read import (
    ACTOR_REPORTS_LIMIT_DEFAULT,
    ACTOR_REPORTS_LIMIT_MAX,
    ACTOR_REPORTS_LIMIT_MIN,
    ActorDetail,
    ActorItem,
    ActorListResponse,
    ReportItem,
    ReportListResponse,
)

router = APIRouter()


# PR #11 Group H — 60/min/user read bucket. Module-level so the
# decorator can reference it without re-resolving the lru_cache.
_limiter = get_limiter()

# Plan "Inherited locks" + §9.3 RBAC matrix: every authenticated
# role can read the actors list. The same tuple is shared across
# the four PR #11 read endpoints so a future policy change has one
# place to update.
_READ_ROLES = ("analyst", "researcher", "policy", "soc", "admin")


@router.get(
    "",
    response_model=ActorListResponse,
    summary="List threat actors (offset-paginated)",
    description=(
        "Returns the list of threat-actor groups (name, MITRE intrusion "
        "set id, aka aliases, description) together with their codenames. "
        "Offset pagination — actors is a small, sort-stable set; keyset "
        "pagination is used for /reports and /incidents (plan D3). "
        "Default sort is `name ASC, id ASC` (plan D11)."
    ),
    responses={
        200: {
            "description": "One page of actors with offset metadata.",
            "content": {
                "application/json": {
                    "examples": {
                        "happy": {
                            "summary": "Three groups, first page",
                            "value": {
                                "items": [
                                    {
                                        "id": 3,
                                        "name": "Lazarus Group",
                                        "mitre_intrusion_set_id": "G0032",
                                        "aka": ["APT38", "Hidden Cobra"],
                                        "description": "DPRK-attributed",
                                        "codenames": ["Andariel", "Bluenoroff"],
                                    }
                                ],
                                "limit": 50,
                                "offset": 0,
                                "total": 3,
                            },
                        },
                        "empty": {
                            "summary": "No groups seeded yet",
                            "value": {
                                "items": [],
                                "limit": 50,
                                "offset": 0,
                                "total": 0,
                            },
                        },
                    }
                }
            },
        },
        401: {"description": "Missing or invalid session cookie"},
        403: {
            "description": (
                "Authenticated role is not analyst / researcher / policy "
                "/ soc / admin"
            )
        },
        422: {
            "description": (
                "Invalid query parameter (limit out of 1..200, offset "
                "negative). Plan D12 — no silent ignore of filter values."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": [
                            {
                                "loc": ["query", "limit"],
                                "msg": (
                                    "Input should be less than or equal to 200"
                                ),
                                "type": "less_than_equal",
                            }
                        ]
                    }
                }
            },
        },
        429: {
            "description": (
                "Rate limit exceeded — 60/min/user read bucket (plan D2). "
                "`Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining` "
                "headers present. Body is the uniform JSON shape pinned by "
                "Group G (`api.rate_limit.rate_limit_exceeded_handler`)."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "error": "rate_limit_exceeded",
                        "message": "60 per 1 minute",
                    }
                }
            },
        },
    },
)
@_limiter.limit("60/minute")
async def list_actors_endpoint(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    session: AsyncSession = Depends(get_db),
    _current_user=Depends(require_role(*_READ_ROLES)),
) -> ActorListResponse:
    """List actors. Plan D12 uniform-422 comes from the ``Query``
    bounds above — FastAPI surfaces validation errors as 422 before
    this handler runs, so the body never touches an out-of-range
    ``limit`` / ``offset``.
    """
    rows, total = await read_repositories.list_actors(
        session, limit=limit, offset=offset
    )
    return ActorListResponse(
        items=[ActorItem.model_validate(row) for row in rows],
        limit=limit,
        offset=offset,
        total=total,
    )


@router.get(
    "/{actor_id}",
    response_model=ActorDetail,
    summary="Get one threat actor (group) with its codenames",
    description=(
        "Shallow-joined detail view of a single threat-actor group. "
        "Returns the core group fields plus the flat codenames list. "
        "Plan D11 excludes traversal into `report_codenames` — this "
        "endpoint does NOT surface reports that mention the actor. "
        "Returns 404 when the actor id is unknown."
    ),
    responses={
        200: {
            "description": "Actor detail with codenames (plan D1 + D11).",
        },
        401: {"description": "Missing or invalid session cookie"},
        403: {"description": "Role not analyst / researcher / policy / soc / admin"},
        404: {
            "description": "Actor id not found",
            "content": {
                "application/json": {
                    "example": {"detail": "actor not found"}
                }
            },
        },
        422: {
            "description": "Invalid path parameter — non-integer actor_id.",
        },
        429: {
            "description": (
                "Rate limit exceeded — 60/min/user per-route bucket."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "error": "rate_limit_exceeded",
                        "message": "60 per 1 minute",
                    }
                }
            },
        },
    },
)
@_limiter.limit("60/minute")
async def get_actor_detail_endpoint(
    request: Request,
    actor_id: int,
    session: AsyncSession = Depends(get_db),
    _current_user: CurrentUser = Depends(require_role(*_READ_ROLES)),
) -> Response:
    """Actor detail (plan D1 + D11)."""
    detail = await detail_aggregator.get_actor_detail(
        session, actor_id=actor_id
    )
    if detail is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "actor not found"},
        )
    return ActorDetail.model_validate(detail)


@router.get(
    "/{actor_id}/reports",
    response_model=ReportListResponse,
    summary="List reports that mention this actor (keyset-paginated)",
    description=(
        "Returns the reports linked to this actor via the "
        "`report_codenames` M:N join. Envelope is identical to "
        "`GET /api/v1/reports` (plan D9 — `{items, next_cursor}`; "
        "no `total`, no `limit` echo). Sort is `published DESC, id "
        "DESC` with a keyset cursor over `(published, id)` (plan D16). "
        "Dedup via EXISTS — a report linked via multiple codenames "
        "appears once (plan D17). Plan D15 empty contract: actor "
        "exists but has no codenames / codenames have no linked "
        "reports / date filter excludes all → `200` with `{items: "
        "[], next_cursor: null}`. Plan D12 regression: the "
        "`/api/v1/actors/{id}` detail endpoint shape is UNCHANGED by "
        "this PR — reports come from this sibling endpoint only."
    ),
    responses={
        200: {
            "description": (
                "One keyset page of reports that mention this actor. "
                "`next_cursor` is `null` on the final page. Empty "
                "pages (D15 b/c/d) return an empty items array with "
                "the same envelope."
            ),
            "content": {
                "application/json": {
                    "examples": {
                        "populated": {
                            "summary": "Actor with 3 linked reports, final page",
                            "value": {
                                "items": [
                                    {
                                        "id": 42,
                                        "title": "Lazarus targets South Korean crypto exchanges",
                                        "url": "https://mandiant.com/blog/lazarus-2026q1",
                                        "url_canonical": "https://mandiant.com/blog/lazarus-2026q1",
                                        "published": "2026-03-15",
                                        "source_id": 7,
                                        "source_name": "Mandiant",
                                        "lang": "en",
                                        "tlp": "WHITE",
                                    }
                                ],
                                "next_cursor": None,
                            },
                        },
                        "empty": {
                            "summary": "Actor exists but has no linked reports (D15 b/c/d)",
                            "value": {"items": [], "next_cursor": None},
                        },
                    }
                }
            },
        },
        401: {"description": "Missing or invalid session cookie"},
        403: {
            "description": (
                "Authenticated role is not analyst / researcher / policy "
                "/ soc / admin"
            )
        },
        404: {
            "description": (
                "Actor id not found (D15(a)). Distinct from the 200 "
                "empty envelope returned when the actor exists but "
                "has no linked reports — analysts rely on the status "
                "code to tell 'unknown actor' from 'known-but-empty'."
            ),
            "content": {
                "application/json": {
                    "example": {"detail": "actor not found"}
                }
            },
        },
        422: {
            "description": (
                "Invalid query parameter — `cursor` malformed, "
                "`limit` out of range, or `date_from` / `date_to` "
                "not ISO-format. Plan D12 — no silent ignore."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": [
                            {
                                "loc": ["query", "cursor"],
                                "msg": "cursor is not valid base64",
                                "type": "value_error.malformed_cursor",
                            }
                        ]
                    }
                }
            },
        },
        429: {
            "description": (
                "Rate limit exceeded — 60/min/user per-route bucket "
                "(plan D6). Bucket is independent of `/actors`, "
                "`/actors/{id}` detail, and `/reports` — draining one "
                "does not consume the others."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "error": "rate_limit_exceeded",
                        "message": "60 per 1 minute",
                    }
                }
            },
        },
    },
)
@_limiter.limit("60/minute")
async def list_actor_reports_endpoint(
    request: Request,
    actor_id: int,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[
        int,
        Query(ge=ACTOR_REPORTS_LIMIT_MIN, le=ACTOR_REPORTS_LIMIT_MAX),
    ] = ACTOR_REPORTS_LIMIT_DEFAULT,
    session: AsyncSession = Depends(get_db),
    _current_user: CurrentUser = Depends(require_role(*_READ_ROLES)),
) -> Response:
    """Reports-mentioning-this-actor list (plan D1 + D6 + D9 + D15–D17).

    Contract notes:

    - **D15(a) 404 vs 200-empty split.** The read module's
      ``_actor_exists`` pre-check runs first; on None return, the
      router surfaces 404 with the same ``{"detail": "actor not
      found"}`` body as ``GET /actors/{id}``. Empty-envelope responses
      (200 + ``{items: [], next_cursor: null}``) cover the other
      three empty branches (no codenames / no report_codenames /
      filter excludes all) — no silent conflation.
    - **Cursor codec reuse.** ``decode_cursor`` / ``encode_cursor``
      from ``api.read.pagination`` — identical to ``/reports`` list.
      Malformed cursor → 422 with the same FastAPI-shaped error body
      (``type: value_error.malformed_cursor``) so FE branches on one
      status for both endpoints.
    - **FastAPI Query bounds** reject ``limit`` out of range and
      malformed ISO dates at the 422 layer before this handler runs.
    """
    cursor_published: date | None = None
    cursor_id: int | None = None
    if cursor is not None:
        try:
            decoded = decode_cursor(cursor)
        except CursorDecodeError as exc:
            return JSONResponse(
                status_code=422,
                content={
                    "detail": [
                        {
                            "loc": ["query", "cursor"],
                            "msg": str(exc),
                            "type": "value_error.malformed_cursor",
                        }
                    ]
                },
            )
        cursor_published = decoded.sort_value
        cursor_id = decoded.last_id

    result = await actor_reports.get_actor_reports(
        session,
        actor_id=actor_id,
        date_from=date_from,
        date_to=date_to,
        cursor_published=cursor_published,
        cursor_id=cursor_id,
        limit=limit,
    )

    # D15(a) — missing actor. Distinct status from the 200-empty
    # branches so analysts can tell "unknown actor" from "known
    # actor with no evidence yet".
    if result is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "actor not found"},
        )

    rows, next_published, next_id = result

    next_cursor: str | None = None
    if next_published is not None and next_id is not None:
        next_cursor = encode_cursor(next_published, next_id)

    return ReportListResponse(
        items=[ReportItem.model_validate(row) for row in rows],
        next_cursor=next_cursor,
    )
