"""Integration tests for POST /api/v1/reports/review/{staging_id}.

Covers (Group F reviewer checklist):

1. Router actually owns ``async with session.begin()`` — verified by
   monkeypatching the service to assert session is mid-transaction
   when called.
2. Exception → HTTP mapping: 404 / 409 / 422 / 422 for the four
   promote errors, all with distinct body shapes.
3. 409 body matches ``AlreadyDecidedError`` DTO exactly — no
   FastAPI ``{"detail": ...}`` wrapper, top-level keys are the DTO
   fields.
4. 422 body does not leak internal exception strings — structured
   JSON with named error codes and bounded field content.
5. RBAC locked to analyst / researcher / admin (401 unauth, 403 for
   policy / soc / unknown roles).

Pydantic validation failures (missing decision_reason on reject,
unknown decision literal) are also tested to prove they surface as
422 via FastAPI's default handling — not 500.

Uses an in-memory aiosqlite DB for the real handler path but
monkeypatches the service layer for exception injection, so the
tests exercise the full router + DTO + DB dependency stack without
requiring pg-specific semantics. Group H is the real-PG equivalent.
"""

from __future__ import annotations

import datetime as dt
from typing import AsyncIterator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from api.promote import service as promote_service
from api.promote.errors import (
    PromoteValidationError,
    StagingAlreadyDecidedError,
    StagingInvalidStateError,
    StagingNotFoundError,
)
from api.promote.service import PromoteOutcome, RejectOutcome
from api.tables import metadata, staging_table


# ---------------------------------------------------------------------------
# DB + ASGI client fixtures (this file overrides conftest's mock db override)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def real_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def review_client(
    real_engine: AsyncEngine, session_store, fake_redis
) -> AsyncIterator[AsyncClient]:
    """ASGI client with:
    - ``get_db`` -> real aiosqlite sessions (not the conftest AsyncMock).
    - ``get_session_store`` -> the shared fake-redis session store
      (so ``make_session_cookie`` works end-to-end for RBAC).
    """
    from api.auth.session import get_session_store
    from api.db import get_db
    from api.main import app

    sessionmaker = async_sessionmaker(real_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_session_store] = lambda: session_store

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


REVIEW_URL = "/api/v1/reports/review/{staging_id}"


async def _seed_pending_staging(engine: AsyncEngine) -> int:
    """Insert one pending staging row and return its id. Uses a
    separate session so the handler's session sees committed data."""
    async with AsyncSession(engine, expire_on_commit=False) as s:
        result = await s.execute(
            sa.insert(staging_table)
            .values(
                url_canonical="http://e.com/test",
                url="http://e.com/test",
                title="Test",
                published=dt.datetime(2026, 4, 17, tzinfo=dt.timezone.utc),
                status="pending",
            )
            .returning(staging_table.c.id)
        )
        staging_id = result.scalar_one()
        await s.commit()
        return staging_id


async def _approve_cookie(make_session_cookie, roles: list[str] | None = None) -> str:
    return await make_session_cookie(roles=roles or ["analyst"])


# ---------------------------------------------------------------------------
# RBAC — 401 unauth, 403 wrong role, 200 allowed roles
# ---------------------------------------------------------------------------


class TestRBAC:
    async def test_without_session_returns_401(
        self, review_client: AsyncClient
    ) -> None:
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=1),
            json={"decision": "approve"},
        )
        assert resp.status_code == 401

    async def test_policy_role_rejected_403(
        self, review_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await make_session_cookie(roles=["policy"])
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=1),
            cookies={"dprk_cti_session": cookie},
            json={"decision": "approve"},
        )
        assert resp.status_code == 403

    @pytest.mark.parametrize("unknown_role", ["viewer", "tester"])
    async def test_unknown_role_rejected_at_session_construction(
        self, make_session_cookie, unknown_role: str
    ) -> None:
        """Unknown realm roles fail ``SessionData`` validation upstream of RBAC.

        Replaces the prior ``test_soc_role_rejected_403`` /
        ``test_unknown_role_rejected_403`` assertions: with the Phase 0
        roles-narrowing deferral closed, ``SessionData.roles`` is
        ``list[KnownRole]`` and pydantic rejects unknowns at construction.
        The RBAC layer therefore never observes a session bearing an
        unknown role — the gate moved up the stack.

        ``soc`` was removed from this parametrize because the canonical
        ``KnownRole`` literal includes it (it sits on ``_READ_ROLES``);
        ``viewer`` and ``tester`` remain genuinely-unknown placeholders.
        """
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            await make_session_cookie(roles=[unknown_role])

    @pytest.mark.parametrize("role", ["analyst", "researcher", "admin"])
    async def test_allowed_roles_reach_handler(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
        role: str,
    ) -> None:
        """Each allowed role must reach the handler and succeed on a
        pending staging row. 200 proves the RBAC gate lets them past,
        AND that no other guard (verify_token etc.) blocks them."""
        staging_id = await _seed_pending_staging(real_engine)
        cookie = await make_session_cookie(roles=[role])
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=staging_id),
            cookies={"dprk_cti_session": cookie},
            json={"decision": "approve"},
        )
        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Happy path — approve + reject end-to-end through the real service
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_approve_returns_200_with_expected_body(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        staging_id = await _seed_pending_staging(real_engine)
        cookie = await _approve_cookie(make_session_cookie)
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=staging_id),
            cookies={"dprk_cti_session": cookie},
            json={"decision": "approve", "notes": "looks good"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["staging_id"] == staging_id
        assert body["status"] == "promoted"
        assert isinstance(body["report_id"], int)
        assert body["report_id"] > 0

    async def test_reject_returns_200_with_null_report_id(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        staging_id = await _seed_pending_staging(real_engine)
        cookie = await _approve_cookie(make_session_cookie)
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=staging_id),
            cookies={"dprk_cti_session": cookie},
            json={
                "decision": "reject",
                "decision_reason": "duplicate of report #42",
                "notes": "discussed in #ops",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["staging_id"] == staging_id
        assert body["status"] == "rejected"
        assert body["report_id"] is None


# ---------------------------------------------------------------------------
# Exception → HTTP mapping (monkeypatched service)
# ---------------------------------------------------------------------------


class TestExceptionMapping:
    """Monkeypatch the service entry points to raise each domain
    exception and verify the router translates to the right status
    code + body shape."""

    async def test_not_found_returns_404(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def _raise(session, **kwargs):
            raise StagingNotFoundError(staging_id=kwargs["staging_id"])

        monkeypatch.setattr(promote_service, "promote_staging_row", _raise)
        cookie = await _approve_cookie(make_session_cookie)
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=999),
            cookies={"dprk_cti_session": cookie},
            json={"decision": "approve"},
        )
        assert resp.status_code == 404
        assert resp.json() == {"error": "not_found", "staging_id": 999}

    async def test_already_promoted_returns_409_with_dto_shape(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        decided_at = dt.datetime(2026, 4, 17, 12, 0, tzinfo=dt.timezone.utc)

        async def _raise(session, **kwargs):
            raise StagingAlreadyDecidedError(
                staging_id=kwargs["staging_id"],
                current_status="promoted",
                decided_by="alice-sub",
                decided_at=decided_at,
            )

        monkeypatch.setattr(promote_service, "promote_staging_row", _raise)
        cookie = await _approve_cookie(make_session_cookie)
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=1),
            cookies={"dprk_cti_session": cookie},
            json={"decision": "approve"},
        )
        assert resp.status_code == 409
        body = resp.json()
        # Top-level keys must match AlreadyDecidedError DTO exactly —
        # NOT wrapped in FastAPI's ``{"detail": ...}`` envelope.
        assert set(body.keys()) == {
            "error",
            "current_status",
            "decided_by",
            "decided_at",
        }
        assert body["error"] == "already_decided"
        assert body["current_status"] == "promoted"
        assert body["decided_by"] == "alice-sub"
        # datetime serialized as ISO string.
        assert body["decided_at"].startswith("2026-04-17T12:00")

    async def test_already_rejected_returns_409(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """409 body must carry current_status='rejected' cleanly —
        proves DTO construction path doesn't reject either reachable
        post-decision state."""

        async def _raise(session, **kwargs):
            raise StagingAlreadyDecidedError(
                staging_id=kwargs["staging_id"],
                current_status="rejected",
                decided_by="bob-sub",
                decided_at=dt.datetime(2026, 4, 17, tzinfo=dt.timezone.utc),
            )

        monkeypatch.setattr(promote_service, "reject_staging_row", _raise)
        cookie = await _approve_cookie(make_session_cookie)
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=1),
            cookies={"dprk_cti_session": cookie},
            json={"decision": "reject", "decision_reason": "x"},
        )
        assert resp.status_code == 409
        body = resp.json()
        assert body["current_status"] == "rejected"

    async def test_invalid_state_returns_422_not_409(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Critical regression guard: StagingInvalidStateError must
        NOT go through the 409 AlreadyDecidedError DTO (whose
        current_status is Literal['promoted','rejected']). Sending
        'approved' through that DTO would 500 via Pydantic validation."""

        async def _raise(session, **kwargs):
            raise StagingInvalidStateError(
                staging_id=kwargs["staging_id"],
                current_status="approved",
            )

        monkeypatch.setattr(promote_service, "promote_staging_row", _raise)
        cookie = await _approve_cookie(make_session_cookie)
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=1),
            cookies={"dprk_cti_session": cookie},
            json={"decision": "approve"},
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body == {
            "error": "invalid_staging_state",
            "staging_id": 1,
            "current_status": "approved",
        }

    async def test_error_state_returns_422(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def _raise(session, **kwargs):
            raise StagingInvalidStateError(
                staging_id=kwargs["staging_id"],
                current_status="error",
            )

        monkeypatch.setattr(promote_service, "promote_staging_row", _raise)
        cookie = await _approve_cookie(make_session_cookie)
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=1),
            cookies={"dprk_cti_session": cookie},
            json={"decision": "approve"},
        )
        assert resp.status_code == 422
        assert resp.json()["current_status"] == "error"

    async def test_promote_validation_error_returns_422(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def _raise(session, **kwargs):
            raise PromoteValidationError(
                staging_id=kwargs["staging_id"],
                reason="title is NULL on staging",
            )

        monkeypatch.setattr(promote_service, "promote_staging_row", _raise)
        cookie = await _approve_cookie(make_session_cookie)
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=1),
            cookies={"dprk_cti_session": cookie},
            json={"decision": "approve"},
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body == {
            "error": "promote_validation_failed",
            "staging_id": 1,
            "reason": "title is NULL on staging",
        }


# ---------------------------------------------------------------------------
# Pydantic-level payload validation (must stay 422, not 500)
# ---------------------------------------------------------------------------


class TestPayloadValidation:
    async def test_missing_decision_returns_422(
        self,
        review_client: AsyncClient,
        make_session_cookie,
    ) -> None:
        cookie = await _approve_cookie(make_session_cookie)
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=1),
            cookies={"dprk_cti_session": cookie},
            json={},
        )
        assert resp.status_code == 422

    async def test_unknown_decision_returns_422(
        self,
        review_client: AsyncClient,
        make_session_cookie,
    ) -> None:
        cookie = await _approve_cookie(make_session_cookie)
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=1),
            cookies={"dprk_cti_session": cookie},
            json={"decision": "maybe"},
        )
        assert resp.status_code == 422

    async def test_reject_without_decision_reason_returns_422(
        self,
        review_client: AsyncClient,
        make_session_cookie,
    ) -> None:
        cookie = await _approve_cookie(make_session_cookie)
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=1),
            cookies={"dprk_cti_session": cookie},
            json={"decision": "reject"},
        )
        assert resp.status_code == 422

    async def test_reject_with_empty_decision_reason_returns_422(
        self,
        review_client: AsyncClient,
        make_session_cookie,
    ) -> None:
        cookie = await _approve_cookie(make_session_cookie)
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=1),
            cookies={"dprk_cti_session": cookie},
            json={"decision": "reject", "decision_reason": ""},
        )
        assert resp.status_code == 422

    async def test_reject_with_whitespace_only_reason_returns_422(
        self,
        review_client: AsyncClient,
        make_session_cookie,
    ) -> None:
        cookie = await _approve_cookie(make_session_cookie)
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=1),
            cookies={"dprk_cti_session": cookie},
            json={"decision": "reject", "decision_reason": "   \t  "},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Transaction ownership — prove the router holds the begin() block
# ---------------------------------------------------------------------------


class TestTransactionOwnership:
    async def test_service_is_called_inside_active_transaction(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        monkeypatch: pytest.MonkeyPatch,
        real_engine: AsyncEngine,
    ) -> None:
        """Plan §2.2 A locks the transaction boundary to the handler.
        We prove it by having the monkeypatched service inspect
        ``session.in_transaction()`` at call time — the router must
        have opened ``async with session.begin()`` before calling us."""
        staging_id = await _seed_pending_staging(real_engine)

        captured = {}

        async def _spy(**kwargs):
            session = kwargs["session"]
            captured["in_transaction"] = session.in_transaction()
            return PromoteOutcome(
                staging_id=kwargs["staging_id"],
                report_id=42,
                attached_existing=False,
                reviewer_sub=kwargs["reviewer_sub"],
            )

        # Make the service signature-compatible by binding the session
        # via the first positional argument the router passes.
        async def _service(session, *, staging_id, reviewer_sub, reviewer_notes):
            return await _spy(
                session=session,
                staging_id=staging_id,
                reviewer_sub=reviewer_sub,
                reviewer_notes=reviewer_notes,
            )

        monkeypatch.setattr(
            promote_service, "promote_staging_row", _service
        )
        cookie = await _approve_cookie(make_session_cookie)
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=staging_id),
            cookies={"dprk_cti_session": cookie},
            json={"decision": "approve"},
        )
        assert resp.status_code == 200
        assert captured["in_transaction"] is True


# ---------------------------------------------------------------------------
# 422 body audit — no internal exception strings over-exposed
# ---------------------------------------------------------------------------


class TestErrorBodySafety:
    async def test_422_body_is_structured_json_not_raw_exception(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Reviewer guard: internal exception strings (traceback, class
        names, repr) must not leak into the client body. Router
        constructs a named-error dict only."""

        async def _raise(session, **kwargs):
            raise PromoteValidationError(
                staging_id=kwargs["staging_id"],
                reason="published is NULL on staging",
            )

        monkeypatch.setattr(promote_service, "promote_staging_row", _raise)
        cookie = await _approve_cookie(make_session_cookie)
        resp = await review_client.post(
            REVIEW_URL.format(staging_id=1),
            cookies={"dprk_cti_session": cookie},
            json={"decision": "approve"},
        )
        body_text = resp.text
        # Negative assertions — none of these should appear in the body.
        assert "Traceback" not in body_text
        assert "PromoteValidationError" not in body_text
        assert "api.promote" not in body_text  # no module path leakage
        # Positive assertion — exactly 3 keys, bounded shape.
        body = resp.json()
        assert set(body.keys()) == {"error", "staging_id", "reason"}
