"""Integration tests for RBAC-gated endpoints.

Tests verify that:
- Unauthenticated requests receive 401
- Authenticated requests with insufficient roles receive 403
- Authenticated requests with the correct role reach the handler (501 stub)
- Non-role-gated endpoints with any valid session return 501

All session management uses fakeredis via the shared fixtures.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# POST /api/v1/alerts/rules — requires admin role
# ---------------------------------------------------------------------------

async def test_alerts_rules_without_session_returns_401(client):
    """POST /alerts/rules without a session cookie returns 401."""
    resp = await client.post("/api/v1/alerts/rules")
    assert resp.status_code == 401


async def test_alerts_rules_with_analyst_session_returns_403(client, make_session_cookie):
    """POST /alerts/rules with analyst role returns 403 (not admin)."""
    cookie = await make_session_cookie(roles=["analyst"])
    resp = await client.post(
        "/api/v1/alerts/rules",
        cookies={"dprk_cti_session": cookie},
    )
    assert resp.status_code == 403


async def test_alerts_rules_with_admin_session_returns_501(client, make_session_cookie):
    """POST /alerts/rules with admin role reaches the handler stub (501)."""
    cookie = await make_session_cookie(roles=["admin"])
    resp = await client.post(
        "/api/v1/alerts/rules",
        cookies={"dprk_cti_session": cookie},
    )
    assert resp.status_code == 501


# ---------------------------------------------------------------------------
# POST /api/v1/ingest/rss/run — requires admin role
# ---------------------------------------------------------------------------

async def test_ingest_rss_run_without_session_returns_401(client):
    """POST /ingest/rss/run without a session cookie returns 401."""
    resp = await client.post("/api/v1/ingest/rss/run")
    assert resp.status_code == 401


async def test_ingest_rss_run_with_analyst_session_returns_403(client, make_session_cookie):
    """POST /ingest/rss/run with analyst role returns 403."""
    cookie = await make_session_cookie(roles=["analyst"])
    resp = await client.post(
        "/api/v1/ingest/rss/run",
        cookies={"dprk_cti_session": cookie},
    )
    assert resp.status_code == 403


async def test_ingest_rss_run_with_admin_session_returns_501(client, make_session_cookie):
    """POST /ingest/rss/run with admin role reaches the handler stub (501)."""
    cookie = await make_session_cookie(roles=["admin"])
    resp = await client.post(
        "/api/v1/ingest/rss/run",
        cookies={"dprk_cti_session": cookie},
    )
    assert resp.status_code == 501


# ---------------------------------------------------------------------------
# GET /api/v1/alerts — any authenticated user (no RBAC guard on list)
# ---------------------------------------------------------------------------

async def test_alerts_list_with_any_authenticated_user_returns_501(client, make_session_cookie):
    """GET /alerts accepts any authenticated user and returns the 501 stub."""
    cookie = await make_session_cookie(roles=["analyst"])
    resp = await client.get(
        "/api/v1/alerts",
        cookies={"dprk_cti_session": cookie},
    )
    # The alerts list endpoint is protected by verify_token (any valid session)
    # but has no role guard, so it reaches the handler stub returning 501.
    assert resp.status_code == 501


async def test_alerts_list_without_session_returns_401(client):
    """GET /alerts without a session cookie returns 401."""
    resp = await client.get("/api/v1/alerts")
    assert resp.status_code == 401


async def test_policy_role_rejected_from_admin_endpoint(client, make_session_cookie):
    """POST /alerts/rules with policy role (non-admin) returns 403."""
    cookie = await make_session_cookie(roles=["policy"])
    resp = await client.post(
        "/api/v1/alerts/rules",
        cookies={"dprk_cti_session": cookie},
    )
    assert resp.status_code == 403
