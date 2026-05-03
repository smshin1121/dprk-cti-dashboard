"""Correlation router — Phase 3 Slice 3 D-1 (PR #28).

See docs/plans/phase-3-slice-3-correlation.md §7.1-§7.5 for the locked
endpoint contract:

    GET /api/v1/analytics/correlation/series   → CorrelationCatalogResponse
    GET /api/v1/analytics/correlation          → CorrelationResponse  (or 422)

Both endpoints are read-only, share the 60/min/user rate limit and the
five-role read RBAC matrix used by the rest of the analytics surface.

The router is intentionally thin per the existing analytics router
precedent: parse query → validate guards → call aggregator → translate
the aggregator's typed exceptions into FastAPI's uniform ``detail[]``
422 envelope (spec §7.3 + §5.1).

Positive lag = X leads Y by k months.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.schemas import CurrentUser
from ..db import get_db
from ..deps import require_role
from ..rate_limit import get_limiter
from ..read.correlation_aggregator import (
    InsufficientSampleError,
    SeriesNotFoundError,
    compute_correlation,
    compute_correlation_series_catalog,
    resolve_default_date_window,
)
from ..schemas.correlation import (
    CorrelationCatalogResponse,
    CorrelationResponse,
)


router = APIRouter()


_limiter = get_limiter()


# Same RBAC matrix as the rest of the analytics + dashboard read surface.
_READ_ROLES = ("analyst", "researcher", "policy", "soc", "admin")


# ---------------------------------------------------------------------------
# /correlation/series — catalog
# ---------------------------------------------------------------------------


@router.get(
    "/correlation/series",
    response_model=CorrelationCatalogResponse,
    summary="D-1 correlation series catalog",
    description=(
        "Returns the list of named time series the correlation endpoint "
        "accepts as `x` / `y`. The FE is expected to render these via "
        "`label_ko` / `label_en` and treat the `id` field as opaque "
        "(spec R-9). Catalog is dynamically derived from existing "
        "dimension tables; the curated baseline is `reports.total` and "
        "`incidents.total`, plus per-motivation / per-sector / "
        "per-country incident series. Disclosure-suppression "
        "(spec R-16) protects sparse-bucket inference at the lag-cell "
        "level, so the catalog is uniform across all 5 read roles."
    ),
)
@_limiter.limit("60/minute")
async def correlation_series_endpoint(
    request: Request,
    session: AsyncSession = Depends(get_db),
    _current_user: CurrentUser = Depends(require_role(*_READ_ROLES)),
) -> CorrelationCatalogResponse:
    raw = await compute_correlation_series_catalog(session)
    return CorrelationCatalogResponse.model_validate(raw)


# ---------------------------------------------------------------------------
# /correlation — primary endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/correlation",
    response_model=CorrelationResponse,
    summary=(
        "D-1 correlation analysis — Pearson + Spearman + lag CCF "
        "(±24 months). Positive lag = X leads Y by k months."
    ),
    description=(
        "Returns the full lag scan (49 cells) for two catalog series "
        "over the requested date window. Each lag carries homogeneous "
        "Pearson and Spearman blocks with raw and BH-FDR-adjusted "
        "p-values; cells outside the BH family carry a typed `reason` "
        "and null metric fields. The response also carries "
        "`interpretation.{caveat, methodology_url, warnings}` per the "
        "structural correlation-≠-causation contract (spec §6).\n\n"
        "Positive lag = X leads Y by k months."
    ),
    responses={
        200: {"description": "Locked CorrelationResponse payload."},
        401: {"description": "Missing or invalid session cookie"},
        403: {"description": "Role not analyst / researcher / policy / soc / admin"},
        422: {
            "description": (
                "Validation error — uniform FastAPI `detail[]` envelope. "
                "`type` discriminator: `value_error.identical_series` (x==y), "
                "`value_error.insufficient_sample` (effective_n < 30), "
                "or plain `value_error` for catalog/date validation."
            ),
            "content": {
                "application/json": {
                    "examples": {
                        "insufficient_sample": {
                            "summary": "effective_n < 30",
                            "value": {
                                "detail": [
                                    {
                                        "loc": ["body", "correlation"],
                                        "msg": (
                                            "Minimum 30 valid months required "
                                            "after no_data exclusion; got 18"
                                        ),
                                        "type": "value_error.insufficient_sample",
                                        "ctx": {
                                            "effective_n": 18,
                                            "minimum_n": 30,
                                        },
                                    }
                                ]
                            },
                        },
                        "identical_series": {
                            "summary": "x and y are identical",
                            "value": {
                                "detail": [
                                    {
                                        "loc": ["query", "y"],
                                        "msg": (
                                            "x and y must be different series IDs"
                                        ),
                                        "type": "value_error.identical_series",
                                        "ctx": {
                                            "x": "reports.total",
                                            "y": "reports.total",
                                        },
                                    }
                                ]
                            },
                        },
                        "series_not_found": {
                            "summary": "x is not in the catalog",
                            "value": {
                                "detail": [
                                    {
                                        "loc": ["query", "x"],
                                        "msg": (
                                            "series id 'foo.bar' not in catalog"
                                        ),
                                        "type": "value_error",
                                    }
                                ]
                            },
                        },
                    }
                }
            },
        },
        429: {"description": "60/min per-user rate limit exceeded"},
    },
)
@_limiter.limit("60/minute")
async def correlation_endpoint(
    request: Request,
    x: Annotated[str, Query(description="Series ID from /correlation/series")],
    y: Annotated[str, Query(description="Series ID from /correlation/series; must differ from x")],
    date_from: Annotated[
        date | None, Query(description="Inclusive lower bound; defaults to DB min")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="Inclusive upper bound; defaults to DB max")
    ] = None,
    alpha: Annotated[
        float,
        Query(
            gt=0.0,
            lt=1.0,
            description=(
                "Significance threshold for `significant` flag (BH-FDR "
                "adjusted). Default 0.05."
            ),
        ),
    ] = 0.05,
    session: AsyncSession = Depends(get_db),
    _current_user: CurrentUser = Depends(require_role(*_READ_ROLES)),
) -> CorrelationResponse:
    # Spec §7.3 + R-15 — identical_series guard before any DB hit.
    if x == y:
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "loc": ["query", "y"],
                    "msg": "x and y must be different series IDs",
                    "type": "value_error.identical_series",
                    "ctx": {"x": x, "y": y},
                }
            ],
        )

    # Default the window to DB min/max per spec §7.3 query-param table.
    # An omitted date_from resolves to ``min(reports.published)`` AND
    # ``min(incidents.reported)`` whichever is earlier; date_to symmetric.
    # This makes the response deterministic for "give me everything"
    # queries instead of drifting with date.today().
    resolved_from, resolved_to = await resolve_default_date_window(
        session, requested_from=date_from, requested_to=date_to
    )
    date_from = resolved_from
    date_to = resolved_to

    if date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "loc": ["query", "date_to"],
                    "msg": "date_to must be on or after date_from",
                    "type": "value_error",
                    "ctx": {
                        "date_from": date_from.isoformat(),
                        "date_to": date_to.isoformat(),
                    },
                }
            ],
        )

    try:
        raw = await compute_correlation(
            session,
            x=x,
            y=y,
            date_from=date_from,
            date_to=date_to,
            alpha=alpha,
        )
    except InsufficientSampleError as exc:
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "loc": ["body", "correlation"],
                    "msg": str(exc),
                    "type": "value_error.insufficient_sample",
                    "ctx": {
                        "effective_n": exc.effective_n,
                        "minimum_n": exc.minimum_n,
                    },
                }
            ],
        ) from exc
    except SeriesNotFoundError as exc:
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "loc": ["query", "x" if exc.series_id == x else "y"],
                    "msg": f"series id {exc.series_id!r} not in catalog",
                    "type": "value_error",
                }
            ],
        ) from exc

    return CorrelationResponse.model_validate(raw)
