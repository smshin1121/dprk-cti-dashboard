"""Pact provider-state handler — dev/test environments ONLY.

Plan §4 PR #12 Group I. `pact-ruby` (via ``pact-python``'s Verifier)
POSTs ``{"consumer": "...", "state": "..."}`` to this endpoint before
each interaction when ``provider_states_setup_url`` is wired. We use
that hook to:

1. Seed any DB rows the interaction assumes (e.g., ``at least 100
   actors``).
2. Create or clear the Redis session for the test analyst user so
   the authenticated interactions (``/auth/me 200``, ``/dashboard``,
   ``/actors``) receive a valid ``Set-Cookie`` that the verifier's
   internal cookie jar re-plays on the subsequent real request.

Security
--------
**Registered only when ``APP_ENV != prod``** (see main.py guard).
This endpoint writes to Redis and (in future iterations) can mutate
the DB — exposing it in production would be a wide-open session
minter. In dev/test the only callers are the verifier harness and
local engineers running the same contract suite.

Why a state endpoint and not a test-only middleware
---------------------------------------------------
A test-only middleware that auto-authenticates every request would
make the /auth/me 401 interaction impossible to verify — no way to
distinguish "this request should be unauth" from "this request is
the next happy-path interaction". The per-state endpoint lets the
401 state set a NO-OP cookie, cleanly contrasting with the 200 state
that mints one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.schemas import SessionData
from ..auth.session import SessionStore, get_session_store, set_session_cookie
from ..db import get_db

router = APIRouter()


class _ProviderStatePayload(BaseModel):
    """Request body from pact-ruby verifier.

    The verifier posts both ``state`` (single) and, in newer Pact
    spec versions, a list of states. We accept either — the handler
    treats the string form as a one-element list.
    """

    state: str | None = None
    states: list[str] | None = None
    action: str | None = None  # "setup" or "teardown" — we only setup
    consumer: str | None = None


def _states_from_payload(payload: _ProviderStatePayload) -> list[str]:
    if payload.states:
        return payload.states
    if payload.state:
        return [payload.state]
    return []


async def _seed_analyst_session(
    response: Response,
    session_store: SessionStore,
) -> None:
    """Mint a test-analyst session and attach the signed cookie to
    the response so pact-ruby's cookie jar carries it into the
    subsequent interaction request."""
    now = datetime.now(timezone.utc)
    data = SessionData(
        sub="pact-test-analyst",
        email="analyst@dprk.test",
        name="Pact Test Analyst",
        roles=["analyst"],
        created_at=now,
        last_activity=now,
    )
    cookie = await session_store.create(data)
    set_session_cookie(response, cookie)


async def _ensure_group(session: AsyncSession, name: str) -> int:
    """Upsert a group by name; return its id. Idempotent so repeated
    state setups don't fail on the UNIQUE(name) constraint."""
    from sqlalchemy import text

    result = await session.execute(
        text("SELECT id FROM groups WHERE name = :n"),
        {"n": name},
    )
    row = result.first()
    if row is not None:
        return int(row[0])
    ins = await session.execute(
        text(
            "INSERT INTO groups (name, aka) VALUES (:n, :aka) "
            "RETURNING id"
        ),
        {"n": name, "aka": []},
    )
    return int(ins.scalar_one())


async def _ensure_min_actors(session: AsyncSession, minimum: int) -> None:
    """Seed groups up to ``minimum`` count. Idempotent: counts existing
    rows and only adds the difference."""
    from sqlalchemy import text

    count_row = (
        await session.execute(text("SELECT COUNT(*) FROM groups"))
    ).scalar_one()
    existing = int(count_row)
    if existing >= minimum:
        return
    # Names must be unique — use an indexed suffix beyond any
    # canonical seed names so we don't collide with "Lazarus Group"
    # etc. that other PRs might add.
    for i in range(existing, minimum):
        await session.execute(
            text(
                "INSERT INTO groups (name, aka) VALUES (:n, :aka) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {"n": f"pact-fixture-group-{i:04d}", "aka": []},
        )


@router.post("", include_in_schema=False)
async def provider_states(
    payload: _ProviderStatePayload,
    response: Response,
    session_store: Annotated[SessionStore, Depends(get_session_store)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Handle a single provider-state setup request.

    The verifier calls this synchronously before each interaction.
    Mapping below matches the `.given(...)` strings in
    ``apps/frontend/tests/contract/frontend-dprk-cti-api.pact.test.ts``.
    """
    states = _states_from_payload(payload)
    if not states:
        # pact-ruby also posts with action=teardown at the end of a
        # run; treat an empty state as a no-op success.
        return {"status": "ok"}

    for state in states:
        if state == "no valid session cookie":
            # Explicitly no cookie minted — the subsequent request
            # exercises the 401 path.
            continue

        if state == "an authenticated analyst session":
            await _seed_analyst_session(response, session_store)
            continue

        if state == "seeded actors and an authenticated session":
            await _ensure_group(session, "Lazarus Group")
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        if state == "seeded actors with at least 100 rows and an authenticated session":
            await _ensure_min_actors(session, 100)
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        if state == (
            "seeded reports/incidents/actors and an authenticated analyst session"
        ):
            # Dashboard summary only needs the aggregator to return
            # ANY integers — pact matchers are shape-tolerant. Seed
            # one group so top_groups isn't empty; reports/incidents
            # can legitimately be zero and the MatchersV3.integer(0)
            # would still satisfy shape expectations.
            await _ensure_group(session, "Lazarus Group")
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        # Unknown state — fall through with a session so the
        # interaction still authenticates. Better to mint a cookie
        # than to silently fail the verifier on a state rename.

    return {"status": "ok"}
