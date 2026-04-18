"""Dashboard router — ``GET /api/v1/dashboard/summary`` (PR #11 Group E).

Plan D6 shape + aggregator in ``api.read.dashboard_aggregator``.
Router stays thin — all query composition lives in the aggregator.

Filter scope reminders (also in the aggregator docstring):

- ``date_from`` / ``date_to`` filter reports AND incidents.
  ``total_actors`` is an inventory count, unfiltered.
- ``group_ids`` filters ``top_groups`` only. Extending it to
  totals would require a correlated EXISTS chain the MVP does
  not need (groups↔reports is N-hop; groups↔incidents is
  disconnected in the schema).
- ``top_n`` bound is [1, 20], default 5 (plan D6).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AfterValidator
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.schemas import CurrentUser
from ..db import get_db
from ..deps import require_role
from ..rate_limit import get_limiter
from ..read.dashboard_aggregator import compute_dashboard_summary
from ..schemas.read import DashboardSummary

router = APIRouter()


# PR #11 Group H — 60/min/user read bucket (see module docstring in
# rate_limit.py). The aggregate query itself is the same six-query
# composition regardless of rate-limit decoration — shape of the
# DashboardSummary DTO is unchanged.
_limiter = get_limiter()

# Plan "Inherited locks" / §9.3 RBAC matrix — same as the other
# three PR #11 read endpoints.
_READ_ROLES = ("analyst", "researcher", "policy", "soc", "admin")


def _validate_group_ids(items: list[int] | None) -> list[int] | None:
    """Enforce per-item ``ge=1`` on the repeatable ``group_id`` param.

    ``Query(ge=1)`` applied to a ``list[int]`` tries to compare the
    bound against the list itself and raises a TypeError at runtime
    (Pydantic v2 rejects the list > int comparison). Per-item
    validation through ``AfterValidator`` sidesteps this and matches
    the plan D12 uniform-422 contract: each invalid id surfaces as
    a 422 with a standard validation-error detail.
    """
    if items is None:
        return None
    for value in items:
        if value < 1:
            raise ValueError("group_id must be >= 1")
    return items


@router.get(
    "/summary",
    response_model=DashboardSummary,
    summary="Dashboard KPI summary",
    description=(
        "Returns scalar totals and three aggregate arrays for the FE "
        "KPI card view (design doc §14 Phase 2 W1-W2). Plan D6 locks "
        "the shape. Filters: `date_from` / `date_to` apply to reports "
        "and incidents; `group_ids` scopes `top_groups` only (incidents "
        "have no direct group FK in the schema); `top_n` bounds the "
        "`top_groups` array length (default 5, max 20)."
    ),
    responses={
        200: {
            "description": "Summary with scalar totals and three aggregate arrays.",
            "content": {
                "application/json": {
                    "examples": {
                        "happy": {
                            "summary": "Populated DB",
                            "value": {
                                "total_reports": 1204,
                                "total_incidents": 154,
                                "total_actors": 12,
                                "reports_by_year": [
                                    {"year": 2024, "count": 318},
                                    {"year": 2023, "count": 287},
                                ],
                                "incidents_by_motivation": [
                                    {"motivation": "disruption", "count": 21},
                                    {"motivation": "espionage", "count": 52},
                                    {"motivation": "financial", "count": 81},
                                ],
                                "top_groups": [
                                    {
                                        "group_id": 3,
                                        "name": "Lazarus Group",
                                        "report_count": 412,
                                    },
                                    {
                                        "group_id": 5,
                                        "name": "Kimsuky",
                                        "report_count": 287,
                                    },
                                ],
                            },
                        },
                        "empty": {
                            "summary": "Fresh / empty DB",
                            "value": {
                                "total_reports": 0,
                                "total_incidents": 0,
                                "total_actors": 0,
                                "reports_by_year": [],
                                "incidents_by_motivation": [],
                                "top_groups": [],
                            },
                        },
                    }
                }
            },
        },
        401: {"description": "Missing or invalid session cookie"},
        403: {"description": "Role not analyst / researcher / policy / soc / admin"},
        422: {
            "description": (
                "Invalid query param — bad ISO date, `top_n` out of 1..20, "
                "negative `group_id`. Plan D12 uniform 422 contract."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": [
                            {
                                "loc": ["query", "top_n"],
                                "msg": (
                                    "Input should be less than or equal to 20"
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
                "Per-route bucket; aggregate totals/arrays remain "
                "unaffected by the decorator when under limit."
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
async def dashboard_summary_endpoint(
    request: Request,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    group_id: Annotated[
        list[int] | None, Query(), AfterValidator(_validate_group_ids)
    ] = None,
    top_n: Annotated[int, Query(ge=1, le=20)] = 5,
    session: AsyncSession = Depends(get_db),
    _current_user: CurrentUser = Depends(require_role(*_READ_ROLES)),
) -> DashboardSummary:
    """Dispatch to the aggregator and wrap in the DTO.

    The query param is spelled ``group_id`` (singular + repeatable
    standard) on the wire for consistency with ``tag`` / ``source``
    / ``country`` on /reports and /incidents. Plan D6 wrote
    ``group_ids`` — the param is the same repeatable list, the name
    is client-facing consistency.
    """
    raw = await compute_dashboard_summary(
        session,
        date_from=date_from,
        date_to=date_to,
        group_ids=group_id,
        top_n=top_n,
    )
    return DashboardSummary.model_validate(raw)
