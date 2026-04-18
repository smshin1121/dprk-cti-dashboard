"""Reports router — /api/v1/reports/...

Endpoints:
- ``GET /api/v1/reports`` — keyset-paginated list with filter surface
  (PR #11 Phase 2.2 Group C).
- ``GET /api/v1/reports/{report_id}/similar`` — 501 stub (Phase 3).
- ``POST /api/v1/reports/review/{staging_id}`` — approve/reject a
  staging row (PR #10 Phase 2.1 Group F).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import AfterValidator
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.schemas import CurrentUser
from ..db import get_db
from ..deps import require_role
from ..rate_limit import get_limiter
from ..promote import service as promote_service
from ..promote.errors import (
    PromoteValidationError,
    StagingAlreadyDecidedError,
    StagingInvalidStateError,
    StagingNotFoundError,
)
from ..read import repositories as read_repositories
from ..read.pagination import CursorDecodeError, decode_cursor, encode_cursor
from ..schemas.read import ReportItem, ReportListResponse
from ..schemas.review import (
    AlreadyDecidedError,
    ApproveRequest,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
)

router = APIRouter()


# RBAC lock per plan §2.1 D5 / design doc §9.3 — review/promote is
# the analyst+researcher+admin triad. soc and policy are read-only
# (their read endpoints land in PR #11). require_role is already
# variadic, so no helper wrapper needed.
ALLOWED_REVIEWER_ROLES = ("analyst", "researcher", "admin")

# PR #11 Group G (mutation 30/min/user) + Group H (read 60/min/user)
# both use this limiter. Decorators live per-endpoint below.
_limiter = get_limiter()

# PR #11 read endpoints expand the triad to all five authenticated
# roles (plan "Inherited locks" + §9.3 RBAC matrix row "View
# WHITE/GREEN").
_READ_ROLES = ("analyst", "researcher", "policy", "soc", "admin")


def _reject_empty_items(items: list[str] | None) -> list[str] | None:
    """Enforce plan D12 on repeatable Query params.

    FastAPI's ``Query(min_length=1)`` constrains the LIST length,
    not each element — so ``?tag=`` arrives as ``[""]`` and passes
    the list-level check. Plan D12 locks uniform 422 for invalid
    filter values including empty strings, so we reject element-
    level empties here. ``AfterValidator`` plumbs the ``ValueError``
    through as a FastAPI 422 with the standard ``detail[]`` shape.
    """
    if items is None:
        return None
    for value in items:
        if not value or not value.strip():
            raise ValueError("each value must be non-empty")
    return items


@router.get(
    "",
    response_model=ReportListResponse,
    summary="List reports (keyset-paginated, filterable)",
    description=(
        "Returns reports sorted by `published DESC, id DESC` (plan D11). "
        "Pagination is keyset-style — clients pass the opaque `next_cursor` "
        "from the previous page to continue (plan D3). Filter params per "
        "plan D5 with OR semantics inside a repeatable (`tag=a&tag=b` "
        "matches either) and AND semantics across different filters "
        "(`tag=a&source=Mandiant` requires both). JOIN uses EXISTS so a "
        "report with two matching tags still surfaces as one row."
    ),
    responses={
        200: {
            "description": "One page of reports with next_cursor metadata.",
            "content": {
                "application/json": {
                    "examples": {
                        "happy": {
                            "summary": "First page, next page exists",
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
                                "next_cursor": "MjAyNi0wMy0xNXw0Mg",
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
                "Invalid query param — malformed cursor, empty filter value, "
                "invalid ISO date, out-of-range limit, etc. Plan D12 locks "
                "uniform 422 with no silent ignore."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": [
                            {
                                "loc": ["query", "cursor"],
                                "msg": "malformed cursor",
                                "type": "value_error.malformed_cursor",
                            }
                        ]
                    }
                }
            },
        },
        429: {
            "description": (
                "Rate limit exceeded — 60/min/user read bucket (plan D2). "
                "Per-route bucket: draining this does NOT consume the "
                "/reports POST-review 30/min mutation bucket."
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
async def list_reports_endpoint(
    request: Request,
    q: Annotated[str | None, Query(min_length=1)] = None,
    tag: Annotated[
        list[str] | None, Query(), AfterValidator(_reject_empty_items)
    ] = None,
    source: Annotated[
        list[str] | None, Query(), AfterValidator(_reject_empty_items)
    ] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    session: AsyncSession = Depends(get_db),
    _current_user: CurrentUser = Depends(require_role(*_READ_ROLES)),
) -> Response:
    """Keyset-paginated reports list.

    ``tag`` / ``source`` repeat query params are validated by FastAPI
    with ``min_length=1`` so ``?tag=`` (empty value) surfaces as 422
    — plan D12 forbids silent ignore. ``date_from`` / ``date_to``
    use Pydantic's ``date`` coercion which rejects malformed ISO
    strings with 422 automatically.

    The cursor is decoded through :func:`api.read.pagination.decode_cursor`.
    Any malformed cursor returns 422 with a body mirroring FastAPI's
    standard validation error shape so FE error handling branches on
    a single status code.
    """
    cursor_published = None
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
        cursor_published = decoded.sort_value
        cursor_id = decoded.last_id

    rows, next_published, next_id = await read_repositories.list_reports(
        session,
        limit=limit,
        cursor_published=cursor_published,
        cursor_id=cursor_id,
        q=q,
        tags=tag,
        sources=source,
        date_from=date_from,
        date_to=date_to,
    )

    next_cursor: str | None = None
    if next_published is not None and next_id is not None:
        next_cursor = encode_cursor(next_published, next_id)

    return ReportListResponse(
        items=[ReportItem.model_validate(row) for row in rows],
        next_cursor=next_cursor,
    )


@router.get("/{report_id}/similar")
async def similar_reports(report_id: int, k: int = 10) -> JSONResponse:
    """§5.2 pgvector similarity search for related reports.

    Stub: returns 501 until Phase 3 analytics work.
    """
    return JSONResponse(
        status_code=501,
        content={
            "status": "not_implemented",
            "endpoint": "reports.similar",
            "report_id": report_id,
            "k": k,
        },
    )


@router.post(
    "/review/{staging_id}",
    response_model=ReviewDecisionResponse,
    responses={
        401: {"description": "Missing or invalid session cookie"},
        403: {"description": "Authenticated role is not analyst / researcher / admin"},
        404: {"description": "Staging row not found"},
        409: {
            "description": "Row already promoted or rejected",
            "model": AlreadyDecidedError,
        },
        422: {
            "description": (
                "Validation error — staging row is in an unhandleable "
                "state (approved / error) or is missing NOT NULL fields"
            )
        },
        429: {
            "description": "Rate limit exceeded — 30/min/user (plan D2 mutation bucket).",
            "content": {
                "application/json": {
                    "example": {
                        "error": "rate_limit_exceeded",
                        "message": "30 per 1 minute",
                    }
                }
            },
        },
    },
)
@_limiter.limit("30/minute")
async def review_staging(
    request: Request,
    staging_id: int,
    payload: ReviewDecisionRequest = Body(...),
    session: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(*ALLOWED_REVIEWER_ROLES)),
) -> Response:
    """§5.3 / §9.3 Approve or reject a staging row.

    Caller owns the transaction: the handler wraps the entire
    decision (service call + any side effects) in a single
    ``async with session.begin():``. Plan §2.2 A locks this boundary
    to the handler so the rollback path on service exceptions is
    uniform regardless of which error surfaces.

    Exception → HTTP mapping (plan §2.2 B response enum lock +
    Group D service-level split):
    - ``StagingNotFoundError``           → 404
    - ``StagingAlreadyDecidedError``     → 409 with ``AlreadyDecidedError``
                                         body (current_status narrowed
                                         to promoted|rejected)
    - ``StagingInvalidStateError``       → 422 (current_status includes
                                         approved|error — not exposed
                                         via the 409 DTO narrowing)
    - ``PromoteValidationError``         → 422 with reason surface

    The error bodies return via ``JSONResponse`` directly (not via
    ``HTTPException``) so we can match the ``AlreadyDecidedError`` DTO
    shape exactly, without FastAPI's default ``{"detail": ...}``
    wrapper obscuring the contract.
    """
    try:
        async with session.begin():
            if isinstance(payload, ApproveRequest):
                outcome = await promote_service.promote_staging_row(
                    session,
                    staging_id=staging_id,
                    reviewer_sub=current_user.sub,
                    reviewer_notes=payload.notes,
                )
                return ReviewDecisionResponse(
                    staging_id=outcome.staging_id,
                    report_id=outcome.report_id,
                    status="promoted",
                )
            # RejectRequest — Pydantic discriminator already narrowed.
            reject_outcome = await promote_service.reject_staging_row(
                session,
                staging_id=staging_id,
                reviewer_sub=current_user.sub,
                decision_reason=payload.decision_reason,
                reviewer_notes=payload.notes,
            )
            return ReviewDecisionResponse(
                staging_id=reject_outcome.staging_id,
                report_id=None,
                status="rejected",
            )
    except StagingNotFoundError as exc:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "staging_id": exc.staging_id},
        )
    except StagingAlreadyDecidedError as exc:
        # Build through the DTO so any shape regression
        # (e.g. current_status narrowing violation) surfaces here
        # as ValidationError rather than producing a 200 with the
        # wrong body. Plan §2.2 B / reviewer warning about response
        # model validation.
        body = AlreadyDecidedError(
            current_status=exc.current_status,
            decided_by=exc.decided_by,
            decided_at=exc.decided_at,
        )
        return JSONResponse(
            status_code=409,
            content=body.model_dump(mode="json"),
        )
    except StagingInvalidStateError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error": "invalid_staging_state",
                "staging_id": exc.staging_id,
                "current_status": exc.current_status,
            },
        )
    except PromoteValidationError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error": "promote_validation_failed",
                "staging_id": exc.staging_id,
                "reason": exc.reason,
            },
        )
