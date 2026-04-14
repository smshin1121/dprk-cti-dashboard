"""Unit tests for api.auth.audit.write_audit.

The DB session is an AsyncMock — no real database is touched.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, call, patch

import pytest
from sqlalchemy import text

from api.auth.audit import write_audit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_session() -> AsyncMock:
    """Return a mock that quacks like AsyncSession."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_write_audit_inserts_row():
    """write_audit() calls session.execute with the expected SQL and bind params."""
    session = _make_mock_session()

    await write_audit(
        session,
        actor="analyst@example.com",
        action="login_success",
        extra={"ip": "127.0.0.1", "user_agent": "pytest/1.0"},
    )

    assert session.execute.called, "session.execute must be called"
    assert session.commit.called, "session.commit must be called after execute"

    # Inspect the positional arguments passed to execute()
    call_args = session.execute.call_args
    sql_arg = call_args[0][0]  # first positional argument = the text() clause
    params_arg = call_args[0][1]  # second positional argument = the params dict

    # Verify core bind params
    assert params_arg["actor"] == "analyst@example.com"
    assert params_arg["action"] == "login_success"
    assert params_arg["entity"] == "auth"
    assert params_arg["entity_id"] is None  # default

    # diff must be valid JSON containing the extra dict
    import json
    diff_parsed = json.loads(params_arg["diff"])
    assert diff_parsed["ip"] == "127.0.0.1"
    assert diff_parsed["user_agent"] == "pytest/1.0"


async def test_write_audit_handles_none_extra():
    """write_audit() with extra=None stores an empty JSON object '{}'."""
    session = _make_mock_session()

    await write_audit(
        session,
        actor="anonymous",
        action="login_failure",
        extra=None,
    )

    call_args = session.execute.call_args
    params_arg = call_args[0][1]

    import json
    diff_parsed = json.loads(params_arg["diff"])
    assert diff_parsed == {}


async def test_audit_failure_does_not_include_raw_exception_message():
    """`_audit_failure` (router helper) must only persist a stable ``reason``
    enum and an optional ``exc_type`` — never the raw exception message.

    Regression for H-3s / HIGH-c2: raw authlib/httpx exceptions could embed
    URLs, key fragments, or PII in ``audit_log.diff_jsonb``.
    """
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from api.routers.auth import _audit_failure

    # Build a Request stub with just the attributes _audit_failure reads.
    request = SimpleNamespace(
        client=SimpleNamespace(host="198.51.100.7"),
        headers={"user-agent": "pytest/audit"},
    )

    captured: dict = {}

    async def _capture_write_audit(db, **kwargs):
        captured.update(kwargs)

    import api.routers.auth as auth_router

    real = auth_router.write_audit
    auth_router.write_audit = _capture_write_audit
    try:
        try:
            raise ValueError(
                "SECRET TOKEN LEAK https://keycloak/token?code=leaked_abc123"
            )
        except ValueError as exc:
            await _audit_failure(
                AsyncMock(), request, "token_exchange_failed", exc_type=type(exc).__name__
            )
    finally:
        auth_router.write_audit = real

    assert captured["action"] == "login_failure"
    extra = captured["extra"]
    # Only these four keys are allowed. No raw exception message should appear.
    assert set(extra.keys()) == {"ip", "user_agent", "reason", "exc_type"}
    assert extra["reason"] == "token_exchange_failed"
    assert extra["exc_type"] == "ValueError"
    # Sanity: the secret-containing error message is NOT in any value.
    for value in extra.values():
        assert value is None or "SECRET TOKEN LEAK" not in str(value)
        assert value is None or "leaked_abc123" not in str(value)


async def test_write_audit_with_entity_and_entity_id():
    """write_audit() passes entity and entity_id through to the SQL params."""
    session = _make_mock_session()

    await write_audit(
        session,
        actor="admin@example.com",
        action="logout",
        entity="auth",
        entity_id="sub-xyz",
    )

    call_args = session.execute.call_args
    params_arg = call_args[0][1]

    assert params_arg["entity"] == "auth"
    assert params_arg["entity_id"] == "sub-xyz"
    assert params_arg["actor"] == "admin@example.com"
    assert params_arg["action"] == "logout"
