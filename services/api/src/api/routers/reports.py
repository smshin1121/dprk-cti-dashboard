"""Reports router — /api/v1/reports/...

Endpoints:
- ``GET /api/v1/reports`` — keyset-paginated list with filter surface
  (PR #11 Phase 2.2 Group C).
- ``GET /api/v1/reports/{report_id}`` — single report detail with
  shallow joins and capped linked_incidents (PR #14 Phase 3 slice 1
  Group A, plan D1 + D9 + D11).
- ``GET /api/v1/reports/{report_id}/similar`` — 501 stub (Phase 3
  slice 1 Group B will implement; plan D2 + D8 + D10).
- ``POST /api/v1/reports/review/{staging_id}`` — approve/reject a
  staging row (PR #10 Phase 2.1 Group F).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import AfterValidator
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.schemas import CurrentUser
from ..db import get_db
from ..deps import get_embedding_client, require_role
from ..embedding_client import (
    LlmProxyEmbeddingClient,
    PermanentEmbeddingError,
)
from ..embedding_writer import embed_report
from ..rate_limit import get_limiter
from ..promote import service as promote_service
from ..promote.errors import (
    PromoteValidationError,
    StagingAlreadyDecidedError,
    StagingInvalidStateError,
    StagingNotFoundError,
)
from ..read import (
    detail_aggregator,
    repositories as read_repositories,
    similar_cache,
    similar_service,
)
from ..read.pagination import CursorDecodeError, decode_cursor, encode_cursor
from ..schemas.read import (
    ReportDetail,
    ReportItem,
    ReportListResponse,
    SIMILAR_K_DEFAULT,
    SIMILAR_K_MAX,
    SIMILAR_K_MIN,
    SimilarReportsResponse,
)
from ..schemas.review import (
    AlreadyDecidedError,
    ApproveRequest,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
)

router = APIRouter()


_embed_logger = logging.getLogger("api.routers.reports.embedding")


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


@router.get(
    "/{report_id}",
    response_model=ReportDetail,
    summary="Get one report with related joins and capped linked incidents",
    description=(
        "Shallow-joined detail view of a single report. Plan D9 caps the "
        "`linked_incidents` collection at 10 newest-reported entries; "
        "reports with > 10 incident links return only the top 10 (ordered "
        "`reported DESC NULLS LAST, id DESC`). `tags`, `codenames`, and "
        "`techniques` are flat string lists. Returns 404 when the report "
        "id is unknown."
    ),
    responses={
        200: {
            "description": "Report detail with shallow joins (plan D9).",
        },
        401: {"description": "Missing or invalid session cookie"},
        403: {"description": "Role not analyst / researcher / policy / soc / admin"},
        404: {
            "description": "Report id not found",
            "content": {
                "application/json": {
                    "example": {"detail": "report not found"}
                }
            },
        },
        422: {
            "description": (
                "Invalid path parameter — non-integer report_id. Plan D12 "
                "uniform 422 (FastAPI path-param validation)."
            ),
        },
        429: {
            "description": (
                "Rate limit exceeded — 60/min/user read bucket (plan D2). "
                "Per-route bucket: this endpoint's drain does NOT consume "
                "the /reports list bucket."
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
async def get_report_detail_endpoint(
    request: Request,
    report_id: int,
    session: AsyncSession = Depends(get_db),
    _current_user: CurrentUser = Depends(require_role(*_READ_ROLES)),
) -> Response:
    """Report detail with linked incidents (plan D1 + D9 + D11).

    Cap on linked_incidents is enforced in SQL by the aggregator (see
    ``detail_aggregator._fetch_linked_incidents``) AND re-checked by
    the DTO's ``Field(max_length=REPORT_DETAIL_INCIDENTS_CAP)``. Both
    layers agree on the same module-level constant — no drift path.
    """
    detail = await detail_aggregator.get_report_detail(
        session, report_id=report_id
    )
    if detail is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "report not found"},
        )
    return ReportDetail.model_validate(detail)


@router.get(
    "/{report_id}/similar",
    response_model=SimilarReportsResponse,
    summary="pgvector Top-k similar reports for a given report",
    description=(
        "Cosine-similarity kNN against `reports.embedding` (migration 0001, "
        "pgvector 1536-dim). Plan D8: self-exclusion, stable `score DESC, "
        "id ASC` sort, `k ∈ [1, 50]` default 10. Plan D10: returns `200` "
        "with `{items: []}` when the source has no embedding or the kNN "
        "yields zero rows — never `500`, never a fake / heuristic "
        "fallback. 5-minute Redis cache keyed on `(report_id, k)` only."
    ),
    responses={
        200: {
            "description": (
                "Top-k most similar reports (plan D8) OR empty list when "
                "the source has no embedding / kNN is empty (plan D10)."
            ),
        },
        401: {"description": "Missing or invalid session cookie"},
        403: {"description": "Role not analyst / researcher / policy / soc / admin"},
        404: {
            "description": "Source report id not found",
            "content": {
                "application/json": {
                    "example": {"detail": "report not found"}
                }
            },
        },
        422: {
            "description": (
                "Invalid path / query param — non-integer report_id, or "
                "`k` outside [1, 50] (plan D8). Plan D12 uniform 422."
            ),
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
async def get_similar_reports_endpoint(
    request: Request,
    report_id: int,
    k: Annotated[int, Query(ge=SIMILAR_K_MIN, le=SIMILAR_K_MAX)] = SIMILAR_K_DEFAULT,
    session: AsyncSession = Depends(get_db),
    redis=Depends(similar_cache.get_redis_for_similar_cache),
    _current_user: CurrentUser = Depends(require_role(*_READ_ROLES)),
) -> Response:
    """Similar-reports endpoint (plan D2 + D8 + D10).

    Flow:
        1. Redis cache lookup on ``(report_id, k)``. Hit → return.
        2. Source existence check → service returns ``found=False``
           → 404.
        3. Service runs pgvector kNN (on PG) or returns empty
           (non-PG dialects — see ``similar_service`` docstring).
        4. Response payload cached for 5 minutes (design doc §7.7).

    Graceful degradation: Redis outages degrade to "no cache" — the
    endpoint still serves correctly, just without the cache speedup.
    D10 forbids 500 on this endpoint; a cache blip is handled inside
    ``similar_cache``.
    """
    cached = await similar_cache.get_cached(
        redis, report_id=report_id, k=k
    )
    if cached is not None:
        return SimilarReportsResponse.model_validate(cached)

    result = await similar_service.get_similar_reports(
        session, source_report_id=report_id, k=k
    )
    if not result.found:
        # Deliberately do NOT cache 404 responses — an unknown id
        # should not occupy a slot.
        return JSONResponse(
            status_code=404,
            content={"detail": "report not found"},
        )

    response_dto = SimilarReportsResponse(items=result.items)
    # Cache the populated or empty (D10) response identically —
    # D10's empty contract IS a valid response shape, and caching it
    # avoids pounding the DB when a source with no embedding gets
    # repeatedly queried by the detail page.
    await similar_cache.set_cached(
        redis,
        report_id=report_id,
        k=k,
        payload=response_dto.model_dump(mode="json"),
    )
    return response_dto


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
    embedding_client: LlmProxyEmbeddingClient | None = Depends(
        get_embedding_client
    ),
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
                # PR #19a Group B — embed-on-promote.
                # Must live INSIDE this ``async with session.begin()``
                # block so the UPDATE participates in the same
                # transaction as the INSERT. PermanentEmbeddingError
                # is caught here to keep the tx-commit path intact
                # (C4 lock): the analyst approve UX must not regress
                # because llm-proxy's contract drifted. Transient
                # failures are swallowed inside ``embed_report`` and
                # therefore never reach this layer.
                if embedding_client is not None:
                    try:
                        await embed_report(
                            session,
                            report_id=outcome.report_id,
                            title=outcome.title,
                            summary=outcome.summary,
                            client=embedding_client,
                        )
                    except PermanentEmbeddingError as exc:
                        _embed_logger.error(
                            "embedding.permanent",
                            extra={
                                "event": "embedding.permanent",
                                "report_id": outcome.report_id,
                                "upstream_status": exc.upstream_status,
                                "reason": exc.reason,
                            },
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
