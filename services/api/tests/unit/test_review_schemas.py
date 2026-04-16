"""Unit tests for ``api.schemas.review`` DTOs.

Contract pinned by docs/plans/pr10-review-promote-api.md §2.1 D1 /
§2.2 A/B/C / §3. The three invariants under test:

1. **approve/reject 분기** — ``decision`` is a tagged discriminator;
   Pydantic picks ``ApproveRequest`` or ``RejectRequest`` from the raw
   dict and rejects any other literal.
2. **decision_reason 필수성** — required + non-empty-after-strip on
   ``RejectRequest``; NOT declared on ``ApproveRequest`` so clients
   sending it get the field silently dropped (plan "approve 시 무시").
3. **notes audit-only** — validates on both shapes but tests verify
   the DTO never stores it in a staging-bound field.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from api.schemas.review import (
    AlreadyDecidedError,
    ApproveRequest,
    DuplicateMatchHint,
    RejectRequest,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    StagingDetail,
    StagingReviewItem,
    StagingReviewListResponse,
)


# ---------------------------------------------------------------------------
# ApproveRequest — decision="approve", no decision_reason
# ---------------------------------------------------------------------------


class TestApproveRequest:
    def test_minimal_validates(self) -> None:
        req = ApproveRequest(decision="approve")
        assert req.decision == "approve"
        assert req.notes is None

    def test_with_notes_validates(self) -> None:
        req = ApproveRequest(decision="approve", notes="looks good")
        assert req.notes == "looks good"

    def test_silently_drops_decision_reason(self) -> None:
        """Extra fields dropped (Pydantic v2 default 'ignore'). Matches
        the plan rule 'approve 시 무시' — client can mis-send the field
        and the service silently discards it rather than persisting it
        in a place the approve path never reads."""
        req = ApproveRequest.model_validate(
            {"decision": "approve", "decision_reason": "stray text"}
        )
        assert not hasattr(req, "decision_reason")
        # Ensure round-trip dict also lacks the field.
        assert "decision_reason" not in req.model_dump()

    def test_wrong_decision_literal_fails(self) -> None:
        with pytest.raises(ValidationError):
            ApproveRequest(decision="reject")  # type: ignore[arg-type]

    def test_notes_length_capped(self) -> None:
        with pytest.raises(ValidationError):
            ApproveRequest(decision="approve", notes="x" * 5001)


# ---------------------------------------------------------------------------
# RejectRequest — decision_reason required non-empty after strip
# ---------------------------------------------------------------------------


class TestRejectRequest:
    def test_minimal_validates(self) -> None:
        req = RejectRequest(decision="reject", decision_reason="spam feed")
        assert req.decision_reason == "spam feed"
        assert req.notes is None

    def test_with_notes_validates(self) -> None:
        req = RejectRequest(
            decision="reject",
            decision_reason="duplicate of report #42",
            notes="see thread in #ops",
        )
        assert req.notes == "see thread in #ops"

    def test_missing_decision_reason_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            RejectRequest.model_validate({"decision": "reject"})
        assert "decision_reason" in str(exc_info.value)

    def test_empty_decision_reason_fails(self) -> None:
        with pytest.raises(ValidationError):
            RejectRequest(decision="reject", decision_reason="")

    def test_whitespace_only_decision_reason_fails(self) -> None:
        """Whitespace-only strings slip past ``min_length=1`` unless the
        validator also strips; this test pins the explicit strip behavior
        so accidentally removing the validator regresses visibly."""
        with pytest.raises(ValidationError) as exc_info:
            RejectRequest(decision="reject", decision_reason="   \t \n  ")
        assert "non-whitespace" in str(exc_info.value)

    def test_decision_reason_stripped(self) -> None:
        """Leading/trailing whitespace normalized — downstream audit
        ``diff_jsonb`` stores the clean form."""
        req = RejectRequest(
            decision="reject", decision_reason="  real reason  "
        )
        assert req.decision_reason == "real reason"

    def test_decision_reason_length_capped(self) -> None:
        with pytest.raises(ValidationError):
            RejectRequest(decision="reject", decision_reason="x" * 5001)


# ---------------------------------------------------------------------------
# Discriminated union — the shape FastAPI uses at the handler boundary
# ---------------------------------------------------------------------------


class TestReviewDecisionRequestUnion:
    _adapter = TypeAdapter(ReviewDecisionRequest)

    def test_approve_dict_resolves_to_approve_request(self) -> None:
        parsed = self._adapter.validate_python({"decision": "approve"})
        assert isinstance(parsed, ApproveRequest)

    def test_reject_dict_resolves_to_reject_request(self) -> None:
        parsed = self._adapter.validate_python(
            {"decision": "reject", "decision_reason": "offtopic"}
        )
        assert isinstance(parsed, RejectRequest)
        assert parsed.decision_reason == "offtopic"

    def test_unknown_decision_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._adapter.validate_python({"decision": "maybe"})

    def test_reject_missing_reason_rejected_through_union(self) -> None:
        with pytest.raises(ValidationError):
            self._adapter.validate_python({"decision": "reject"})


# ---------------------------------------------------------------------------
# Response shapes — ReviewDecisionResponse, AlreadyDecidedError
# ---------------------------------------------------------------------------


class TestReviewDecisionResponse:
    def test_promoted_with_report_id(self) -> None:
        resp = ReviewDecisionResponse(
            staging_id=7, report_id=42, status="promoted"
        )
        assert resp.report_id == 42

    def test_rejected_has_null_report_id(self) -> None:
        resp = ReviewDecisionResponse(
            staging_id=7, report_id=None, status="rejected"
        )
        assert resp.report_id is None

    def test_pending_status_rejected(self) -> None:
        """Response enum narrowed to reachable post-decision states
        (plan §2.2 B). ``pending`` is a pre-decision state."""
        with pytest.raises(ValidationError):
            ReviewDecisionResponse(
                staging_id=7, report_id=None, status="pending"  # type: ignore[arg-type]
            )

    def test_approved_status_rejected(self) -> None:
        """``approved`` is in the staging CHECK enum (migration 0002)
        but the PR #10 endpoint never drives the row into that state.
        The response DTO therefore must not expose it."""
        with pytest.raises(ValidationError):
            ReviewDecisionResponse(
                staging_id=7, report_id=None, status="approved"  # type: ignore[arg-type]
            )


class TestAlreadyDecidedError:
    def test_full_body(self) -> None:
        err = AlreadyDecidedError(
            current_status="promoted",
            decided_by="alice",
            decided_at=datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc),
        )
        assert err.error == "already_decided"
        assert err.current_status == "promoted"

    def test_approved_current_status_rejected(self) -> None:
        """409 body must not surface ``approved`` — plan §2.2 B locks the
        enum to the two states the endpoint actually emits."""
        with pytest.raises(ValidationError):
            AlreadyDecidedError(
                current_status="approved",  # type: ignore[arg-type]
                decided_by="alice",
                decided_at=datetime.now(timezone.utc),
            )


# ---------------------------------------------------------------------------
# Frozen-model immutability (repo-wide style rule)
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_approve_request_is_frozen(self) -> None:
        req = ApproveRequest(decision="approve")
        with pytest.raises(ValidationError):
            req.notes = "tamper"  # type: ignore[misc]

    def test_reject_request_is_frozen(self) -> None:
        req = RejectRequest(decision="reject", decision_reason="dup")
        with pytest.raises(ValidationError):
            req.decision_reason = "actually keep"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Read DTOs
# ---------------------------------------------------------------------------


class TestStagingReviewItem:
    def test_minimal_shape(self) -> None:
        now = datetime.now(timezone.utc)
        item = StagingReviewItem(
            id=1,
            created_at=now,
            source_id=None,
            source_name=None,
            title="t",
            url="http://example.com",
            url_canonical="http://example.com/",
            published=None,
            lang=None,
            confidence=None,
            status="pending",
        )
        assert item.status == "pending"

    def test_status_accepts_full_staging_enum(self) -> None:
        """List endpoint may surface non-pending rows for operational
        views (rejected/promoted filters), so the DTO enum is the full
        CHECK (pending/approved/rejected/promoted/error) — unlike the
        decided-surface DTOs."""
        for status in ("pending", "approved", "rejected", "promoted", "error"):
            StagingReviewItem(
                id=1,
                created_at=datetime.now(timezone.utc),
                source_id=None,
                source_name=None,
                title=None,
                url=None,
                url_canonical="urn:stix:x--y",
                published=None,
                lang=None,
                confidence=None,
                status=status,
            )


class TestStagingDetail:
    def test_duplicate_matches_defaults_empty(self) -> None:
        detail = StagingDetail(
            id=1,
            created_at=datetime.now(timezone.utc),
            source_id=None,
            source_name=None,
            url=None,
            url_canonical="urn:stix:x--y",
            sha256_title=None,
            title=None,
            raw_text=None,
            lang=None,
            published=None,
            summary=None,
            confidence=None,
            status="pending",
            reviewed_by=None,
            reviewed_at=None,
            decision_reason=None,
            promoted_report_id=None,
            error=None,
        )
        assert detail.duplicate_matches == []

    def test_duplicate_match_hint_shape(self) -> None:
        hint = DuplicateMatchHint(
            match_type="url_canonical",
            report_id=99,
            report_title="existing",
            report_published=datetime(2026, 1, 1).date(),
        )
        assert hint.match_type == "url_canonical"


class TestStagingReviewListResponse:
    def test_default_cursor_none(self) -> None:
        resp = StagingReviewListResponse(items=[])
        assert resp.next_cursor is None

    def test_with_cursor(self) -> None:
        resp = StagingReviewListResponse(items=[], next_cursor="opaque-b64")
        assert resp.next_cursor == "opaque-b64"
