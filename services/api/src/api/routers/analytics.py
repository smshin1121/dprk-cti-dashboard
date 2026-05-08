"""Analytics router — PR #13 Phase 2.4 plan D2 + PR #23 Phase 3.5 §6.A.

Read-only endpoints that feed the dashboard visualizations layer:

    GET /api/v1/analytics/attack_matrix    → AttackMatrixResponse  (PR #13)
    GET /api/v1/analytics/trend            → TrendResponse         (PR #13)
    GET /api/v1/analytics/geo              → GeoResponse           (PR #13)
    GET /api/v1/analytics/incidents_trend  → IncidentsTrendResponse (PR #23)

All endpoints share the ``date_from`` / ``date_to`` / ``group_id[]``
query contract with ``/dashboard/summary``. Rate limit is the same
60/min per-user bucket as PR #11 read endpoints (plan D2 lock). RBAC
matches the rest of the read surface — analyst / researcher / policy /
soc / admin. Aggregation lives in ``api.read.analytics_aggregator``;
this router stays thin.

The four §5.4 design-doc stubs (``/attack-heatmap``,
``/attribution-graph``, ``/geopolitical``, ``/forecast``) that lived
here before PR #13 were Phase 3+ placeholders returning 501. They are
dropped; the Phase 3 implementation will land with its own plan and
fresh DTOs.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AfterValidator
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.schemas import CurrentUser
from ..db import get_db
from ..deps import require_role
from ..rate_limit import get_limiter
from ..read.analytics_aggregator import (
    compute_actor_network,
    compute_attack_matrix,
    compute_geo,
    compute_incidents_trend,
    compute_trend,
)
from ..schemas.read import (
    INCIDENTS_TREND_UNKNOWN_KEY,
    ActorNetworkResponse,
    AttackMatrixResponse,
    GeoResponse,
    IncidentsTrendResponse,
    TrendResponse,
)

router = APIRouter()


_limiter = get_limiter()


# Plan §9.3 RBAC matrix — same as the other read endpoints (dashboard,
# reports, incidents, actors).
_READ_ROLES = ("analyst", "researcher", "policy", "soc", "admin")


def _validate_group_ids(items: list[int] | None) -> list[int] | None:
    """Per-item ``ge=1`` validation on the repeatable ``group_id`` param.

    Carried verbatim from ``dashboard.py`` — see its docstring for the
    Pydantic v2 ``Query(ge=...)`` + ``list[int]`` collision this
    sidesteps.
    """
    if items is None:
        return None
    for value in items:
        if value < 1:
            raise ValueError("group_id must be >= 1")
    return items


# ---------------------------------------------------------------------------
# Shared response example blocks — 429 is identical across the three
# endpoints; 401 / 403 are fully shape-equivalent. Declaring them here
# keeps the three responses dicts below readable without duplicating
# the same example payload three times.
# ---------------------------------------------------------------------------

_RESPONSES_COMMON_AUTH: dict[int | str, dict[str, object]] = {
    401: {"description": "Missing or invalid session cookie"},
    403: {"description": "Role not analyst / researcher / policy / soc / admin"},
    429: {
        "description": (
            "Rate limit exceeded — same 60/min/user policy as other "
            "read endpoints (dashboard, reports, incidents, actors) "
            "but a per-decorated-route bucket. Exhausting "
            "/analytics/attack_matrix does NOT consume /analytics/trend "
            "or /dashboard/summary budget."
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
}

_RESPONSES_422_COMMON: dict[str, object] = {
    "description": (
        "Invalid query param — bad ISO date, negative ``group_id``, "
        "or numeric cap out of ``1..200`` (``top_n`` on "
        "``/attack_matrix``; ``top_n_actor`` / ``top_n_tool`` / "
        "``top_n_sector`` on ``/actor_network``). Plan D12 uniform "
        "422 contract."
    ),
    "content": {
        "application/json": {
            "example": {
                "detail": [
                    {
                        "loc": ["query", "group_id"],
                        "msg": "group_id must be >= 1",
                        "type": "value_error",
                    }
                ]
            }
        }
    },
}


# ---------------------------------------------------------------------------
# /attack_matrix
# ---------------------------------------------------------------------------


@router.get(
    "/attack_matrix",
    response_model=AttackMatrixResponse,
    summary="ATT&CK tactic × technique matrix",
    description=(
        "Returns a row-based tactic × technique count matrix over the "
        "filter window. Response shape: ``{tactics: [], rows: "
        "[{tactic_id, techniques: [{technique_id, count}]}]}``. "
        "``count`` is distinct report count per technique. ``top_n`` "
        "(default 30, max 200) caps the number of techniques returned "
        "across the whole matrix, ordered by count desc. Techniques "
        "with a null tactic are filtered out. Plan D2 + D8."
    ),
    responses={
        200: {
            "description": "Tactic × technique matrix payload.",
            "content": {
                "application/json": {
                    "examples": {
                        "happy": {
                            "summary": "Populated matrix",
                            "value": {
                                "tactics": [
                                    {"id": "TA0001", "name": "TA0001"},
                                    {"id": "TA0002", "name": "TA0002"},
                                ],
                                "rows": [
                                    {
                                        "tactic_id": "TA0001",
                                        "techniques": [
                                            {"technique_id": "T1566", "count": 18},
                                            {"technique_id": "T1190", "count": 7},
                                        ],
                                    },
                                    {
                                        "tactic_id": "TA0002",
                                        "techniques": [
                                            {"technique_id": "T1059", "count": 12},
                                        ],
                                    },
                                ],
                            },
                        },
                        "empty": {
                            "summary": "No matching techniques",
                            "value": {"tactics": [], "rows": []},
                        },
                    }
                }
            },
        },
        **_RESPONSES_COMMON_AUTH,
        422: _RESPONSES_422_COMMON,
    },
)
@_limiter.limit("60/minute")
async def attack_matrix_endpoint(
    request: Request,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    group_id: Annotated[
        list[int] | None, Query(), AfterValidator(_validate_group_ids)
    ] = None,
    top_n: Annotated[int, Query(ge=1, le=200)] = 30,
    session: AsyncSession = Depends(get_db),
    _current_user: CurrentUser = Depends(require_role(*_READ_ROLES)),
) -> AttackMatrixResponse:
    raw = await compute_attack_matrix(
        session,
        date_from=date_from,
        date_to=date_to,
        group_ids=group_id,
        top_n=top_n,
    )
    return AttackMatrixResponse.model_validate(raw)


# ---------------------------------------------------------------------------
# /trend
# ---------------------------------------------------------------------------


@router.get(
    "/trend",
    response_model=TrendResponse,
    summary="Monthly report volume trend",
    description=(
        "Distinct report count per calendar month of "
        "``reports.published`` within the filter window. Bucket format "
        "is ``YYYY-MM``. Zero-count months are omitted, not "
        "zero-filled — the FE owns gap handling. Plan D2."
    ),
    responses={
        200: {
            "description": "Monthly trend payload.",
            "content": {
                "application/json": {
                    "examples": {
                        "happy": {
                            "summary": "Three months of data",
                            "value": {
                                "buckets": [
                                    {"month": "2026-01", "count": 41},
                                    {"month": "2026-02", "count": 38},
                                    {"month": "2026-03", "count": 47},
                                ]
                            },
                        },
                        "empty": {
                            "summary": "No reports in window",
                            "value": {"buckets": []},
                        },
                    }
                }
            },
        },
        **_RESPONSES_COMMON_AUTH,
        422: _RESPONSES_422_COMMON,
    },
)
@_limiter.limit("60/minute")
async def trend_endpoint(
    request: Request,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    group_id: Annotated[
        list[int] | None, Query(), AfterValidator(_validate_group_ids)
    ] = None,
    session: AsyncSession = Depends(get_db),
    _current_user: CurrentUser = Depends(require_role(*_READ_ROLES)),
) -> TrendResponse:
    raw = await compute_trend(
        session,
        date_from=date_from,
        date_to=date_to,
        group_ids=group_id,
    )
    return TrendResponse.model_validate(raw)


# ---------------------------------------------------------------------------
# /geo
# ---------------------------------------------------------------------------


@router.get(
    "/geo",
    response_model=GeoResponse,
    summary="Country-aggregated incident count",
    description=(
        "Distinct incident count per ``country_iso2`` within the "
        "filter window (filter applies to ``incidents.reported``). "
        "``group_id[]`` is accepted for API uniformity but is a no-op "
        "for this endpoint — the schema has no path from incidents to "
        "groups. DPRK (``KP``) is a plain country row when present; "
        "no special-case field (plan D2 + D7 lock; the FE owns the "
        "map highlight)."
    ),
    responses={
        200: {
            "description": "Country-aggregated incident payload.",
            "content": {
                "application/json": {
                    "examples": {
                        "happy": {
                            "summary": "Three countries",
                            "value": {
                                "countries": [
                                    {"iso2": "KR", "count": 18},
                                    {"iso2": "US", "count": 9},
                                    {"iso2": "KP", "count": 2},
                                ]
                            },
                        },
                        "empty": {
                            "summary": "No incidents in window",
                            "value": {"countries": []},
                        },
                    }
                }
            },
        },
        **_RESPONSES_COMMON_AUTH,
        422: _RESPONSES_422_COMMON,
    },
)
@_limiter.limit("60/minute")
async def geo_endpoint(
    request: Request,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    group_id: Annotated[
        list[int] | None, Query(), AfterValidator(_validate_group_ids)
    ] = None,
    session: AsyncSession = Depends(get_db),
    _current_user: CurrentUser = Depends(require_role(*_READ_ROLES)),
) -> GeoResponse:
    raw = await compute_geo(
        session,
        date_from=date_from,
        date_to=date_to,
        group_ids=group_id,
    )
    return GeoResponse.model_validate(raw)


# ---------------------------------------------------------------------------
# /incidents_trend — PR #23 Group A C1 (lazarus.day parity)
# ---------------------------------------------------------------------------


@router.get(
    "/incidents_trend",
    response_model=IncidentsTrendResponse,
    summary="Monthly incidents trend, sliced by motivation or sector",
    description=(
        "Distinct incidents per calendar month of ``incidents.reported`` "
        "within the filter window, sliced by motivation or sector via "
        "the required ``group_by`` query parameter "
        "(``motivation`` | ``sector``). Outer ``count`` per bucket "
        "is the distinct incident total; ``series`` counts category "
        "memberships and may sum above the outer count for multi-"
        "category incidents. Incidents with no junction row land in a "
        "sentinel ``key='unknown'`` slice rather than being dropped. "
        "Distinct from ``/analytics/trend`` because the "
        "fact table is ``incidents`` (not ``reports``); the two "
        "endpoints answer different analytical questions and do not "
        "share an envelope. Plan PR #23 C1 lock."
    ),
    responses={
        200: {
            "description": "Incidents trend payload, sliced by axis.",
            "content": {
                "application/json": {
                    "examples": {
                        "motivation_populated": {
                            "summary": (
                                "Motivation slice — two months of data"
                            ),
                            "value": {
                                "buckets": [
                                    {
                                        "month": "2026-01",
                                        "count": 14,
                                        "series": [
                                            {"key": "Espionage", "count": 9},
                                            {"key": "Finance", "count": 5},
                                        ],
                                    },
                                    {
                                        "month": "2026-02",
                                        "count": 16,
                                        "series": [
                                            {"key": "Espionage", "count": 10},
                                            {"key": "Finance", "count": 4},
                                            {
                                                "key": INCIDENTS_TREND_UNKNOWN_KEY,
                                                "count": 2,
                                            },
                                        ],
                                    },
                                ],
                                "group_by": "motivation",
                            },
                        },
                        "sector_populated": {
                            "summary": (
                                "Sector slice — one month, three sectors"
                            ),
                            "value": {
                                "buckets": [
                                    {
                                        "month": "2026-03",
                                        "count": 4,
                                        "series": [
                                            {"key": "ENE", "count": 1},
                                            {"key": "FIN", "count": 1},
                                            {"key": "GOV", "count": 2},
                                        ],
                                    }
                                ],
                                "group_by": "sector",
                            },
                        },
                        "empty": {
                            "summary": "No incidents in window",
                            "value": {"buckets": [], "group_by": "motivation"},
                        },
                    }
                }
            },
        },
        **_RESPONSES_COMMON_AUTH,
        422: _RESPONSES_422_COMMON,
    },
)
@_limiter.limit("60/minute")
async def incidents_trend_endpoint(
    request: Request,
    group_by: Annotated[
        Literal["motivation", "sector"],
        Query(
            description=(
                "Required slice axis. ``motivation`` joins "
                "``incident_motivations``; ``sector`` joins "
                "``incident_sectors``. Anything else is 422."
            ),
        ),
    ],
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    group_id: Annotated[
        list[int] | None,
        Query(
            description=(
                "Accepted for filter-surface uniformity with the other "
                "analytics endpoints, but ``incidents_trend`` is a "
                "documented no-op for ``group_id`` — the schema has no "
                "path from ``incidents`` to ``groups`` (same constraint "
                "as ``/analytics/geo`` and the "
                "``incidents_by_motivation`` aggregate on "
                "``/dashboard/summary``). Group-aware incident filters "
                "depend on a future drill-down view per plan §6.C C13."
            ),
        ),
        AfterValidator(_validate_group_ids),
    ] = None,
    session: AsyncSession = Depends(get_db),
    _current_user: CurrentUser = Depends(require_role(*_READ_ROLES)),
) -> IncidentsTrendResponse:
    raw = await compute_incidents_trend(
        session,
        group_by=group_by,
        date_from=date_from,
        date_to=date_to,
        group_ids=group_id,
    )
    return IncidentsTrendResponse.model_validate(raw)


# ---------------------------------------------------------------------------
# /actor_network — PR 3 SNA co-occurrence (plan v1.4 L1)
# ---------------------------------------------------------------------------


@router.get(
    "/actor_network",
    response_model=ActorNetworkResponse,
    summary="Actor-tool / actor-sector / actor-actor co-occurrence graph",
    description=(
        "Returns the SNA co-occurrence graph backing the dashboard "
        "``actor-network-graph`` widget. Three edge classes computed "
        "with ``COUNT(DISTINCT)`` weights: actor↔tool (via shared "
        "report), actor↔sector (via the 5-table chain incident_sectors "
        "→ incidents → incident_sources → reports → report_codenames "
        "→ codenames), and actor↔actor (self-join on report_codenames "
        "with unordered pair canonicalization). Node IDs are kind-"
        "prefixed: ``actor:<group_id>``, ``tool:<technique_id>``, "
        "``sector:<sector_code>``. ``cap_breached`` flag fires when "
        "len(selected actors with eligible degree >= 1) > "
        "``top_n_actor`` per plan v1.4 L4 Step B + L7(b). Filter "
        "contract matches sibling analytics endpoints; per-route "
        "60/min/user rate-limit bucket."
    ),
    responses={
        200: {
            "description": "Actor-network graph payload.",
            "content": {
                "application/json": {
                    "examples": {
                        "happy": {
                            "summary": "Populated graph",
                            "value": {
                                "nodes": [
                                    {
                                        "id": "actor:3",
                                        "kind": "actor",
                                        "label": "Lazarus Group",
                                        "degree": 12,
                                    },
                                    {
                                        "id": "tool:42",
                                        "kind": "tool",
                                        "label": "Phishing",
                                        "degree": 5,
                                    },
                                ],
                                "edges": [
                                    {
                                        "source_id": "actor:3",
                                        "target_id": "tool:42",
                                        "weight": 8,
                                    }
                                ],
                                "cap_breached": False,
                            },
                        },
                        "empty": {
                            "summary": "No co-occurrence in window",
                            "value": {
                                "nodes": [],
                                "edges": [],
                                "cap_breached": False,
                            },
                        },
                    }
                }
            },
        },
        **_RESPONSES_COMMON_AUTH,
        422: _RESPONSES_422_COMMON,
    },
)
@_limiter.limit("60/minute")
async def actor_network_endpoint(
    request: Request,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    group_id: Annotated[
        list[int] | None, Query(), AfterValidator(_validate_group_ids)
    ] = None,
    top_n_actor: Annotated[int, Query(ge=1, le=200)] = 25,
    top_n_tool: Annotated[int, Query(ge=1, le=200)] = 25,
    top_n_sector: Annotated[int, Query(ge=1, le=200)] = 25,
    session: AsyncSession = Depends(get_db),
    _current_user: CurrentUser = Depends(require_role(*_READ_ROLES)),
) -> ActorNetworkResponse:
    raw = await compute_actor_network(
        session,
        date_from=date_from,
        date_to=date_to,
        group_ids=group_id,
        top_n_actor=top_n_actor,
        top_n_tool=top_n_tool,
        top_n_sector=top_n_sector,
    )
    return ActorNetworkResponse.model_validate(raw)
