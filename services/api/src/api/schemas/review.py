"""Pydantic DTOs for PR #10 staging review / promote API.

Design contracts locked in docs/plans/pr10-review-promote-api.md §2.1 D1,
§2.2 A/B/C, §3 In scope (DTO list). Three hard constraints:

1. ``decision`` is a tagged discriminator — APPROVE and REJECT are
   different shapes. APPROVE does not carry ``decision_reason``; REJECT
   requires it (non-empty, whitespace-stripped).
2. Reviewer ``notes`` exist on both shapes but are **audit-only** —
   the promote/reject service writes them to
   ``audit_log.diff_jsonb.reviewer_notes`` and never to a staging
   column. No staging schema migration carries ``notes``.
3. ``ReviewDecisionResponse.status`` and
   ``AlreadyDecidedError.current_status`` are narrowed to the
   *reachable* post-decision states ``{"promoted", "rejected"}``. The
   underlying ``staging.status`` CHECK enum also includes ``pending`` /
   ``approved`` / ``error`` (migration 0002), but the PR #10 review
   endpoint can only transition ``pending → promoted | rejected``, so
   exposing the broader enum would let clients handle states the
   endpoint never emits.

Request DTOs use ``extra='ignore'`` (Pydantic v2 default) — a client
POSTing ``{"decision": "approve", "decision_reason": "..."}`` validates
successfully and ``decision_reason`` is silently dropped, matching the
"approve 시 무시" (ignore on approve) rule. If we later want to surface
misuse, flip this to ``extra='forbid'`` — it is a one-line change with
no API semantics shift, only stricter 422 feedback.

All DTOs are ``frozen=True`` (Pydantic v2 model config) so callers
cannot mutate a validated request/response in flight, matching the
immutability discipline used elsewhere in the repo.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Shared enums / aliases
# ---------------------------------------------------------------------------

# The staging CHECK constraint (migration 0002) allows all five values.
# Queue listings may want to surface any of them for operational views,
# so the READ surface uses the full enum. The DECIDED surface (response
# + 409 conflict body) narrows to the two states the PR #10 endpoint
# actually emits.
StagingStatus = Literal["pending", "approved", "rejected", "promoted", "error"]
DecidedStatus = Literal["promoted", "rejected"]


# ---------------------------------------------------------------------------
# Request: ReviewDecisionRequest = ApproveRequest | RejectRequest
# ---------------------------------------------------------------------------

class ApproveRequest(BaseModel):
    """POST body for approve: promotes the staging row to ``reports``.

    ``decision_reason`` is intentionally not declared here. Clients that
    send it get it silently dropped (plan §2.1 D1 "approve 시 무시"):
    approve has no semantic "reason" — the approval itself is the
    action. ``notes`` is optional and lands in
    ``audit_log.diff_jsonb.reviewer_notes``.
    """

    model_config = ConfigDict(frozen=True)

    decision: Literal["approve"]
    notes: Annotated[str | None, Field(default=None, max_length=5000)] = None


class RejectRequest(BaseModel):
    """POST body for reject: soft-rejects the staging row.

    ``decision_reason`` is required and non-empty after whitespace
    stripping — a reject with no reason is unsafe (audit forensics
    require the cause). ``notes`` is optional and audit-only.

    Reopen (``rejected → pending``) is a future admin-only action, out
    of PR #10 scope (plan §3 Out of scope, §2.2 C).
    """

    model_config = ConfigDict(frozen=True)

    decision: Literal["reject"]
    decision_reason: Annotated[str, Field(min_length=1, max_length=5000)]
    notes: Annotated[str | None, Field(default=None, max_length=5000)] = None

    @field_validator("decision_reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError(
                "decision_reason must contain non-whitespace characters"
            )
        return stripped


# Pydantic v2 tagged union. FastAPI resolves the discriminator
# automatically when this is annotated on a handler parameter.
ReviewDecisionRequest = Annotated[
    ApproveRequest | RejectRequest,
    Field(discriminator="decision"),
]


# ---------------------------------------------------------------------------
# Response: ReviewDecisionResponse (200), AlreadyDecidedError (409)
# ---------------------------------------------------------------------------

class ReviewDecisionResponse(BaseModel):
    """200 body for both approve and reject. Minimal shape by design
    (plan §8 #2 lock): clients reading from ``staging`` / ``reports``
    directly don't need the service to re-serialize the full row.

    ``report_id`` is populated on approve (new or attached_existing),
    ``None`` on reject.
    """

    model_config = ConfigDict(frozen=True)

    staging_id: int
    report_id: int | None
    status: DecidedStatus


class AlreadyDecidedError(BaseModel):
    """409 body when the staging row is no longer ``pending``.

    ``current_status`` is narrowed to ``promoted|rejected`` — the only
    states the PR #10 endpoint can drive the row into (plan §2.2 B). If
    a future flow introduces ``approved`` as an intermediate state, the
    reachable-state enum here must widen in lock-step.
    """

    model_config = ConfigDict(frozen=True)

    error: Literal["already_decided"] = "already_decided"
    current_status: DecidedStatus
    decided_by: str
    decided_at: datetime


# ---------------------------------------------------------------------------
# Read DTOs: StagingReviewItem (list), StagingDetail (detail), hints
# ---------------------------------------------------------------------------

class StagingReviewItem(BaseModel):
    """Item row for ``GET /staging/review``.

    The list endpoint orders by ``created_at ASC, id ASC`` (FIFO, plan
    §2.1 D1 lock) so this DTO intentionally does NOT expose a
    server-chosen ranking field — ordering is contract, not data.

    ``status`` carries the full ``StagingStatus`` because the list
    endpoint accepts ``?status=`` filters for other states
    (operational views of rejected / promoted).
    """

    model_config = ConfigDict(frozen=True)

    id: int
    created_at: datetime
    source_id: int | None
    source_name: str | None
    title: str | None
    url: str | None
    url_canonical: str
    published: datetime | None
    lang: str | None
    confidence: Decimal | None
    status: StagingStatus


class DuplicateMatchHint(BaseModel):
    """One pre-existing ``reports`` row that may overlap with this
    staging row, surfaced on the detail view to help the reviewer
    spot duplicates before approving.

    ``match_type`` enumerates the lookup that found the match:
    ``url_canonical`` (exact canonical URL hit, the UNIQUE dedup key)
    or ``sha256_title_source_scoped`` (same title hash within the same
    source — the bootstrap ETL fallback). No title-only global match
    is surfaced (too noisy — generic headlines collide).
    """

    model_config = ConfigDict(frozen=True)

    match_type: Literal["url_canonical", "sha256_title_source_scoped"]
    report_id: int
    report_title: str
    report_published: date


class StagingDetail(BaseModel):
    """Response body for ``GET /staging/{id}``.

    Surfaces the raw staging columns plus duplicate-match hints so the
    reviewer has enough context to decide without additional queries.
    LLM-filled columns (``summary`` / ``tags_jsonb`` / ``embedding``)
    are included when non-NULL but Phase 2 staging has them all NULL
    — Phase 4 enrichment is the trigger (plan §2.3 LLM-filled scope).
    """

    model_config = ConfigDict(frozen=True)

    id: int
    created_at: datetime
    source_id: int | None
    source_name: str | None
    url: str | None
    url_canonical: str
    sha256_title: str | None
    title: str | None
    raw_text: str | None
    lang: str | None
    published: datetime | None
    summary: str | None
    confidence: Decimal | None
    status: StagingStatus
    reviewed_by: str | None
    reviewed_at: datetime | None
    decision_reason: str | None
    promoted_report_id: int | None
    error: str | None
    duplicate_matches: list[DuplicateMatchHint] = Field(default_factory=list)


class StagingReviewListResponse(BaseModel):
    """Envelope for ``GET /staging/review`` — FIFO page + opaque cursor.

    Cursor is an opaque string (base64-encoded ``(created_at, id)``
    tuple) so the server retains freedom to evolve the pagination
    implementation. The DTO leaves ``next_cursor`` as ``None`` when
    the current page is the last.
    """

    model_config = ConfigDict(frozen=True)

    items: list[StagingReviewItem]
    next_cursor: str | None = None


__all__ = [
    "AlreadyDecidedError",
    "ApproveRequest",
    "DecidedStatus",
    "DuplicateMatchHint",
    "RejectRequest",
    "ReviewDecisionRequest",
    "ReviewDecisionResponse",
    "StagingDetail",
    "StagingReviewItem",
    "StagingReviewListResponse",
    "StagingStatus",
]
