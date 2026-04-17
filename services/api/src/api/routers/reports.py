"""Reports router — /api/v1/reports/...

Endpoints:
- ``GET /api/v1/reports/{report_id}/similar`` — 501 stub (Phase 3).
- ``POST /api/v1/reports/review/{staging_id}`` — approve/reject a
  staging row (PR #10 Phase 2.1 Group F).
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.schemas import CurrentUser
from ..db import get_db
from ..deps import require_role
from ..promote import service as promote_service
from ..promote.errors import (
    PromoteValidationError,
    StagingAlreadyDecidedError,
    StagingInvalidStateError,
    StagingNotFoundError,
)
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
    },
)
async def review_staging(
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
