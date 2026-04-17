"""Staging router — GET /api/v1/staging/...

Endpoints:
- ``GET /api/v1/staging/review`` — FIFO queue listing with cursor
  pagination and status filter.
- ``GET /api/v1/staging/{staging_id}`` — single staging row detail
  with pre-existing-reports duplicate hints.

Read-only surface for PR #10 Phase 2.1 Group E. The write side
(approve / reject) lives on ``routers.reports.review_staging``.

Invariants (plan §2.1 D1 + §2.2 lock):
- Ordering is ``created_at ASC, id ASC`` — FIFO queue for reviewers,
  tie-breaking on id so pagination is stable when two ingest rows
  share a timestamp (DB clock granularity or bulk-insert batch).
- Cursor pagination is ``(created_at, id)`` keyset — opaque
  base64-encoded string. No OFFSET: late-arriving rows do not shift
  the page index the client already saw.
- Duplicate hints on detail: primary ``url_canonical`` (the canonical
  UNIQUE dedup key), secondary ``sha256_title_source_scoped`` only
  (same title hash within the same source, mirroring the bootstrap
  ETL's source-scoped title fallback). No global title match — too
  noisy against generic headlines.
- Detail DTO never carries ``notes`` or any audit-only field; audit
  provenance is a separate surface (``audit_log``) kept out of the
  row shape to keep the DTO contract tight.

RBAC: same analyst / researcher / admin triad as the write side,
per design doc §9.3 and plan §2.1 D5.
"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.schemas import CurrentUser
from ..db import get_db
from ..deps import require_role
from ..rate_limit import get_limiter
from ..schemas.review import (
    DuplicateMatchHint,
    StagingDetail,
    StagingReviewItem,
    StagingReviewListResponse,
    StagingStatus,
)
from ..tables import reports_table, sources_table, staging_table

router = APIRouter()

# Same RBAC triad as routers.reports.review_staging (plan §2.1 D5 /
# design doc §9.3). Kept as a private constant here rather than
# imported from the reports router to avoid a cross-router dep — the
# two modules are narrowly coupled and either could evolve.
_ALLOWED_REVIEWER_ROLES = ("analyst", "researcher", "admin")

# PR #11 Group G — 30/min/user (plan D2 mutation bucket). Staging GET
# endpoints share the reviewer workflow rate so a bot walking the
# queue cannot drain the pool faster than a human reviewer would.
_limiter = get_limiter()


# ---------------------------------------------------------------------------
# Cursor codec — opaque base64(f"{created_at_iso}|{id}")
# ---------------------------------------------------------------------------


def _encode_cursor(created_at: datetime, row_id: int) -> str:
    """Encode a keyset cursor. Round-trip through base64 so clients
    treat it as opaque and the server can evolve the format later
    without breaking old bookmarks (at which point this returns a
    clearly malformed string that the decoder rejects with 400)."""
    raw = f"{created_at.isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


class MalformedCursorError(ValueError):
    """Raised by ``_decode_cursor`` on garbled input. The handler
    catches and returns a 400 with the shared ``{"error": ...}``
    top-level shape used by the rest of the endpoint's error bodies.
    HTTPException was avoided to keep the body shape consistent with
    404 / 409 / 422 responses (FastAPI wraps HTTPException detail in
    ``{"detail": ...}``, which would break the contract)."""


def _decode_cursor(cursor: str) -> tuple[datetime, int]:
    """Decode an opaque cursor into ``(created_at, id)``.

    Raises ``MalformedCursorError`` on malformed input — the cursor
    is a contract boundary, and a garbled one from a stale client
    should surface loudly, not silently fall back to page 1.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        ca_str, id_str = raw.rsplit("|", 1)
        return datetime.fromisoformat(ca_str), int(id_str)
    except (ValueError, UnicodeDecodeError) as exc:
        raise MalformedCursorError(str(exc)) from None


# ---------------------------------------------------------------------------
# GET /staging/review — FIFO queue listing
# ---------------------------------------------------------------------------


@router.get(
    "/review",
    response_model=StagingReviewListResponse,
    responses={
        400: {"description": "Malformed cursor"},
        401: {"description": "Missing or invalid session cookie"},
        403: {"description": "Authenticated role not analyst/researcher/admin"},
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
async def list_pending_review(
    request: Request,
    status: Annotated[StagingStatus, Query()] = "pending",
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    session: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(*_ALLOWED_REVIEWER_ROLES)),
) -> StagingReviewListResponse | JSONResponse:
    """List staging rows in FIFO order.

    Default ``status=pending`` surfaces the review queue. Operational
    views (``rejected`` / ``promoted``) accept the same cursor
    pagination but the cursor is only valid within the same status
    query — switching mid-page may skip or re-show rows.

    FIFO contract (plan §2.1 D1): ``ORDER BY created_at ASC, id ASC``.
    Cursor is keyset-style ``(created_at, id) > (ca, id)`` so
    pagination is stable against inserts that land after the client
    fetched page 1.
    """
    stmt = (
        sa.select(
            staging_table.c.id,
            staging_table.c.created_at,
            staging_table.c.source_id,
            sources_table.c.name.label("source_name"),
            staging_table.c.title,
            staging_table.c.url,
            staging_table.c.url_canonical,
            staging_table.c.published,
            staging_table.c.lang,
            staging_table.c.confidence,
            staging_table.c.status,
        )
        .select_from(
            staging_table.outerjoin(
                sources_table,
                staging_table.c.source_id == sources_table.c.id,
            )
        )
        .where(staging_table.c.status == status)
        .order_by(staging_table.c.created_at.asc(), staging_table.c.id.asc())
        .limit(limit + 1)  # +1 to peek at the next page
    )

    if cursor is not None:
        try:
            cursor_ca, cursor_id = _decode_cursor(cursor)
        except MalformedCursorError as exc:
            return JSONResponse(
                status_code=400,
                content={"error": "malformed_cursor", "message": str(exc)},
            )
        stmt = stmt.where(
            (staging_table.c.created_at > cursor_ca)
            | (
                (staging_table.c.created_at == cursor_ca)
                & (staging_table.c.id > cursor_id)
            )
        )

    result = await session.execute(stmt)
    rows = list(result.all())

    has_more = len(rows) > limit
    page_rows = rows[:limit]

    items = [
        StagingReviewItem(
            id=row.id,
            created_at=row.created_at,
            source_id=row.source_id,
            source_name=row.source_name,
            title=row.title,
            url=row.url,
            url_canonical=row.url_canonical,
            published=row.published,
            lang=row.lang,
            confidence=row.confidence,
            status=row.status,
        )
        for row in page_rows
    ]

    next_cursor: str | None = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)

    return StagingReviewListResponse(items=items, next_cursor=next_cursor)


# ---------------------------------------------------------------------------
# GET /staging/{staging_id} — single-row detail + duplicate hints
# ---------------------------------------------------------------------------


async def _find_duplicate_matches(
    session: AsyncSession,
    *,
    url_canonical: str,
    sha256_title: str | None,
    source_id: int | None,
) -> list[DuplicateMatchHint]:
    """Collect pre-existing ``reports`` rows that may overlap with the
    staging row.

    Primary match: ``reports.url_canonical == staging.url_canonical``
    (UNIQUE, at most one row). Always surfaced when present.

    Secondary match: ``reports.sha256_title == staging.sha256_title``
    AND ``reports.source_id == staging.source_id``. Only surfaced
    when BOTH staging columns are present — sha256 alone across
    sources creates false positives on templated headlines (same
    issue bootstrap's source-scoped fallback was designed to avoid).

    Dedup by ``report_id``: if the same reports row matches both
    criteria, only the ``url_canonical`` hint is emitted (stronger
    signal).
    """
    hints: list[DuplicateMatchHint] = []
    seen_ids: set[int] = set()

    # Primary: url_canonical
    url_result = await session.execute(
        sa.select(
            reports_table.c.id,
            reports_table.c.title,
            reports_table.c.published,
        ).where(reports_table.c.url_canonical == url_canonical)
    )
    for row in url_result.all():
        hints.append(
            DuplicateMatchHint(
                match_type="url_canonical",
                report_id=row.id,
                report_title=row.title,
                report_published=row.published,
            )
        )
        seen_ids.add(row.id)

    # Secondary: sha256_title + source_id (both required).
    if sha256_title and source_id is not None:
        sha_result = await session.execute(
            sa.select(
                reports_table.c.id,
                reports_table.c.title,
                reports_table.c.published,
            ).where(
                (reports_table.c.sha256_title == sha256_title)
                & (reports_table.c.source_id == source_id)
            )
        )
        for row in sha_result.all():
            if row.id in seen_ids:
                continue
            hints.append(
                DuplicateMatchHint(
                    match_type="sha256_title_source_scoped",
                    report_id=row.id,
                    report_title=row.title,
                    report_published=row.published,
                )
            )
            seen_ids.add(row.id)

    return hints


@router.get(
    "/{staging_id}",
    response_model=StagingDetail,
    responses={
        401: {"description": "Missing or invalid session cookie"},
        403: {"description": "Authenticated role not analyst/researcher/admin"},
        404: {"description": "Staging row not found"},
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
async def get_staging_detail(
    request: Request,
    staging_id: Annotated[int, Path(ge=1)],
    session: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(*_ALLOWED_REVIEWER_ROLES)),
) -> JSONResponse | StagingDetail:
    """Return one staging row plus duplicate-match hints.

    The DTO carries ONLY the staging row's columns (plus
    source_name by join and duplicate_matches by query). Audit-log
    provenance — including reviewer ``notes`` — is deliberately
    excluded. ``notes`` is not a staging column (migration 0008
    locked the schema to ``decision_reason`` only) and surfacing
    audit rows through the row DTO would blur the row-vs-event
    contract enforced by plan §2.1 D1 / §2.2 C.
    """
    stmt = (
        sa.select(
            staging_table.c.id,
            staging_table.c.created_at,
            staging_table.c.source_id,
            sources_table.c.name.label("source_name"),
            staging_table.c.url,
            staging_table.c.url_canonical,
            staging_table.c.sha256_title,
            staging_table.c.title,
            staging_table.c.raw_text,
            staging_table.c.lang,
            staging_table.c.published,
            staging_table.c.summary,
            staging_table.c.confidence,
            staging_table.c.status,
            staging_table.c.reviewed_by,
            staging_table.c.reviewed_at,
            staging_table.c.decision_reason,
            staging_table.c.promoted_report_id,
            staging_table.c.error,
        )
        .select_from(
            staging_table.outerjoin(
                sources_table,
                staging_table.c.source_id == sources_table.c.id,
            )
        )
        .where(staging_table.c.id == staging_id)
    )
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "staging_id": staging_id},
        )

    duplicate_matches = await _find_duplicate_matches(
        session,
        url_canonical=row.url_canonical,
        sha256_title=row.sha256_title,
        source_id=row.source_id,
    )

    return StagingDetail(
        id=row.id,
        created_at=row.created_at,
        source_id=row.source_id,
        source_name=row.source_name,
        url=row.url,
        url_canonical=row.url_canonical,
        sha256_title=row.sha256_title,
        title=row.title,
        raw_text=row.raw_text,
        lang=row.lang,
        published=row.published,
        summary=row.summary,
        confidence=row.confidence,
        status=row.status,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        decision_reason=row.decision_reason,
        promoted_report_id=row.promoted_report_id,
        error=row.error,
        duplicate_matches=duplicate_matches,
    )
