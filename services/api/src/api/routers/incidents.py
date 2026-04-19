"""Incidents router — ``GET /api/v1/incidents`` (PR #11 Group D).

Endpoints:
- ``GET /api/v1/incidents`` — keyset-paginated list (PR #11 Group D).
- ``GET /api/v1/incidents/{incident_id}`` — single incident detail
  with flat motivations/sectors/countries and capped linked_reports
  list (PR #14 Phase 3 slice 1 Group A; plan D1 + D9 + D11).

Plan §2.3 matrix:
- keyset cursor ``(reported DESC, id DESC)`` (D3 / D11)
- filters: ``date_from`` / ``date_to``, ``motivation[]`` / ``sector[]``
  / ``country[]`` (D5, repeatable = OR inside, AND across)
- RBAC: 5-role inherited lock
- rate-limit: 60/min/user read bucket attached in Group H
  (independent of /actors, /reports GET, /dashboard buckets —
  slowapi scopes per decorated route)

Country filter enforces ISO 3166-1 alpha-2 at the Query layer (plan
D12 — invalid filter values cannot silently ignore). Validator
normalizes case to uppercase so ``?country=kr`` and ``?country=KR``
match identically against the DB's uppercase storage.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import AfterValidator
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.schemas import CurrentUser
from ..db import get_db
from ..deps import require_role
from ..rate_limit import get_limiter
from ..read import detail_aggregator, repositories as read_repositories
from ..read.pagination import CursorDecodeError, decode_cursor, encode_cursor
from ..schemas.read import IncidentDetail, IncidentItem, IncidentListResponse

router = APIRouter()


# PR #11 Group H — 60/min/user read bucket (see module docstring).
_limiter = get_limiter()

# Plan "Inherited locks" / §9.3 RBAC matrix. Shared across PR #11
# read endpoints — actors / reports / incidents / dashboard.
_READ_ROLES = ("analyst", "researcher", "policy", "soc", "admin")


def _reject_empty_items(items: list[str] | None) -> list[str] | None:
    """Same contract as routers/reports.py::_reject_empty_items.

    Lives here rather than being shared out of a helper module
    because the two read routers are the only call sites for now
    and duplicating the 4-line validator is cheaper than a shared
    module consumers have to import across the API. If a third
    endpoint needs it, promote to ``api.read.validators``.
    """
    if items is None:
        return None
    for value in items:
        if not value or not value.strip():
            raise ValueError("each value must be non-empty")
    return items


_ISO_ALPHA2 = re.compile(r"^[A-Za-z]{2}$")


def _validate_iso_alpha2(items: list[str] | None) -> list[str] | None:
    """Enforce ISO 3166-1 alpha-2 on repeatable ``country`` values
    (plan D5 / D12).

    ``?country=KR`` → normalized to ``["KR"]``; ``?country=korea`` or
    ``?country=`` (empty) → 422. Uppercase normalization means the
    DB comparison succeeds even if clients send mixed-case values.
    """
    if items is None:
        return None
    normalized: list[str] = []
    for value in items:
        if not value or not _ISO_ALPHA2.match(value):
            raise ValueError(
                "country must be ISO 3166-1 alpha-2 (two letters)"
            )
        normalized.append(value.upper())
    return normalized


@router.get(
    "",
    response_model=IncidentListResponse,
    summary="List incidents (keyset-paginated, filterable)",
    description=(
        "Returns incidents sorted by `reported DESC, id DESC` (plan D11). "
        "Each row carries flattened `motivations`, `sectors`, `countries` "
        "arrays aggregated from the three join tables via correlated "
        "scalar subqueries — an incident with multiple matching rows "
        "surfaces exactly once. Filters: `date_from`, `date_to`, "
        "repeatable `motivation` / `sector` / `country`. Repeatable "
        "filters are OR inside a group and AND across groups (plan D5). "
        "Null-reported incidents are excluded — cursor pagination needs "
        "a date value (Phase 3 detail endpoints can expose them)."
    ),
    responses={
        200: {
            "description": "One page of incidents with next_cursor metadata.",
            "content": {
                "application/json": {
                    "examples": {
                        "happy": {
                            "summary": "First page, next page exists",
                            "value": {
                                "items": [
                                    {
                                        "id": 18,
                                        "reported": "2024-05-02",
                                        "title": "Axie Ronin bridge exploit",
                                        "description": "620M USD compromise",
                                        "est_loss_usd": 620000000,
                                        "attribution_confidence": "HIGH",
                                        "motivations": ["financial"],
                                        "sectors": ["crypto"],
                                        "countries": ["SG", "VN"],
                                    }
                                ],
                                "next_cursor": "MjAyNC0wNS0wMnwxOA",
                            },
                        },
                        "last_page": {
                            "summary": "Final page — no next_cursor",
                            "value": {"items": [], "next_cursor": None},
                        },
                    }
                }
            },
        },
        401: {"description": "Missing or invalid session cookie"},
        403: {"description": "Role not analyst / researcher / policy / soc / admin"},
        422: {
            "description": (
                "Invalid query param — bad ISO date, non-alpha-2 country, "
                "empty filter value, malformed cursor, out-of-range limit. "
                "Plan D12 uniform 422 contract."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": [
                            {
                                "loc": ["query", "country", 0],
                                "msg": (
                                    "country must be ISO 3166-1 alpha-2 "
                                    "(two letters)"
                                ),
                                "type": "value_error",
                            }
                        ]
                    }
                }
            },
        },
        429: {
            "description": (
                "Rate limit exceeded — 60/min/user read bucket (plan D2). "
                "Per-route bucket, independent of the other three read "
                "endpoints (slowapi scopes per decorated route)."
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
async def list_incidents_endpoint(
    request: Request,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    motivation: Annotated[
        list[str] | None, Query(), AfterValidator(_reject_empty_items)
    ] = None,
    sector: Annotated[
        list[str] | None, Query(), AfterValidator(_reject_empty_items)
    ] = None,
    country: Annotated[
        list[str] | None, Query(), AfterValidator(_validate_iso_alpha2)
    ] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    session: AsyncSession = Depends(get_db),
    _current_user: CurrentUser = Depends(require_role(*_READ_ROLES)),
) -> Response:
    """Keyset-paginated incidents list.

    Cursor decode errors map to 422 with FastAPI's standard
    HTTPValidationError body shape (plan D12).
    """
    cursor_reported = None
    cursor_id = None
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
        cursor_reported = decoded.sort_value
        cursor_id = decoded.last_id

    rows, next_reported, next_id = await read_repositories.list_incidents(
        session,
        limit=limit,
        cursor_reported=cursor_reported,
        cursor_id=cursor_id,
        date_from=date_from,
        date_to=date_to,
        motivations=motivation,
        sectors=sector,
        countries=country,
    )

    next_cursor: str | None = None
    if next_reported is not None and next_id is not None:
        next_cursor = encode_cursor(next_reported, next_id)

    return IncidentListResponse(
        items=[IncidentItem.model_validate(row) for row in rows],
        next_cursor=next_cursor,
    )


@router.get(
    "/{incident_id}",
    response_model=IncidentDetail,
    summary="Get one incident with flat N:M arrays and capped linked reports",
    description=(
        "Shallow-joined detail view of a single incident. Plan D9 caps "
        "the `linked_reports` collection at 20 newest-published entries "
        "(ordered `published DESC, id DESC`). `motivations`, `sectors`, "
        "and `countries` are flat string lists aggregated from the three "
        "N:M join tables. Unlike the list endpoint, this detail endpoint "
        "surfaces `reported=NULL` rows (detail views do not paginate). "
        "Returns 404 when the incident id is unknown."
    ),
    responses={
        200: {
            "description": "Incident detail with shallow joins (plan D9).",
        },
        401: {"description": "Missing or invalid session cookie"},
        403: {"description": "Role not analyst / researcher / policy / soc / admin"},
        404: {
            "description": "Incident id not found",
            "content": {
                "application/json": {
                    "example": {"detail": "incident not found"}
                }
            },
        },
        422: {
            "description": "Invalid path parameter — non-integer incident_id.",
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
async def get_incident_detail_endpoint(
    request: Request,
    incident_id: int,
    session: AsyncSession = Depends(get_db),
    _current_user: CurrentUser = Depends(require_role(*_READ_ROLES)),
) -> Response:
    """Incident detail with linked reports (plan D1 + D9 + D11)."""
    detail = await detail_aggregator.get_incident_detail(
        session, incident_id=incident_id
    )
    if detail is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "incident not found"},
        )
    return IncidentDetail.model_validate(detail)
