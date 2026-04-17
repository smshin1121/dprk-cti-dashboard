"""Actors router — ``GET /api/v1/actors``.

Single-endpoint router (plan §2.3 Endpoint/Decision matrix). Offset
pagination — plan D3 keeps actors off keyset because the group
count is small and sort-stable under inserts. Default sort
``name ASC, id ASC`` per plan D11 lives in the repository layer.

RBAC: all five roles (analyst / researcher / policy / soc / admin)
read this endpoint per plan "Inherited locks" and §9.3.

Filter surface: intentionally empty (plan D5). Detail endpoint
(``/actors/{id}``) is plan D9 deferred to Phase 3.

Rate limit (plan D2): 60/min/user decoration lands in Group H once
the slowapi + Redis infrastructure is in place (Group F). This
module stays rate-limit-unaware so Group F's middleware can attach
externally without rewriting the handler signature.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import require_role
from ..read import repositories as read_repositories
from ..schemas.read import ActorItem, ActorListResponse

router = APIRouter()


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
            )
        },
        429: {
            "description": (
                "Rate limit exceeded (60/min/user). `Retry-After` and "
                "`X-RateLimit-Remaining` headers present. Attached in "
                "Group H once slowapi + Redis (Group F) lands."
            )
        },
    },
)
async def list_actors_endpoint(
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
