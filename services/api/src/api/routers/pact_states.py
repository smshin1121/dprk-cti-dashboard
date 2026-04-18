"""Pact provider-state handler — dev/test environments ONLY.

Plan §4 PR #12 Group I. `pact-ruby` (via ``pact-python``'s Verifier)
POSTs ``{"consumer": "...", "state": "..."}`` to this endpoint before
each interaction when ``provider_states_setup_url`` is wired. We use
that hook to:

1. Seed DB rows the interaction assumes — and, crucially, seed them
   in the SHAPE the FE pact matchers require. A matcher like
   ``eachLike({aka: eachLike('APT38')})`` rejects empty arrays and
   null fields; an actor row missing ``mitre_intrusion_set_id`` or
   carrying ``aka = []`` breaks live verification.
2. Create or clear the Redis session for the test analyst user so
   the authenticated interactions (``/auth/me 200``, ``/dashboard``,
   ``/actors``) receive a valid ``Set-Cookie`` that the verifier's
   internal cookie jar re-plays on the subsequent real request.

Security
--------
**Registered only when ``APP_ENV != prod``** (see main.py guard).
This endpoint writes to Redis and mutates DB rows on an unauthenticated
request. Exposing it in production would be a wide-open session
minter plus a free DB-insert surface. In dev/test the only callers
are the verifier harness, the Playwright E2E CI job, and local
engineers running the same contract suite.

Seeding shape discipline
------------------------
Every fixture row satisfies the STRICTEST matcher the FE pact uses
for that endpoint. Examples:

- ``/actors`` pact uses ``eachLike({aka: eachLike('APT38'),
  description: string('...'), mitre_intrusion_set_id: string('G0032'),
  codenames: eachLike('Andariel')})``. Therefore EVERY actor row we
  seed carries a non-null ``mitre_intrusion_set_id``, a non-empty
  ``aka`` array, a non-null ``description``, AND at least one
  linked codename.
- ``/dashboard/summary`` pact uses ``eachLike`` on all three
  aggregate arrays — we seed at least one report (populates
  ``reports_by_year``), one incident + motivation (populates
  ``incidents_by_motivation``), and a report-codename-group chain
  (populates ``top_groups``).

Idempotency
-----------
State requests fire before EVERY interaction, so the same state
name may be invoked multiple times in a single verify run. All
upserts use ``ON CONFLICT DO NOTHING`` or guarded
``SELECT-then-INSERT`` so repeats are safe.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import text
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


# ---------------------------------------------------------------------------
# DB fixture helpers
# ---------------------------------------------------------------------------
#
# Each helper is idempotent. The caller composes them into a state
# setup. Layering:
#
#   _ensure_source           ← FK target for reports
#   _ensure_full_group       ← groups row with aka + description + mitre id
#   _ensure_codename         ← codenames row linked to a group
#   _ensure_report_with_link ← reports row + report_codenames FK row
#   _ensure_incident_with_motivation
#                            ← incidents row + incident_motivations row
#   _ensure_min_actors       ← bulk-seed filler actors to `minimum`
#
# None of these commit — the router-level endpoint does the single
# commit at the end of a state request so partial failures don't
# leave the DB in a mixed state.


async def _ensure_source(session: AsyncSession) -> int:
    """Upsert the `pact-fixture-source` source row; returns its id."""
    existing = (
        await session.execute(
            text("SELECT id FROM sources WHERE name = :n"),
            {"n": "pact-fixture-source"},
        )
    ).first()
    if existing is not None:
        return int(existing[0])
    row = await session.execute(
        text(
            "INSERT INTO sources (name, type) VALUES (:n, :t) "
            "RETURNING id"
        ),
        {"n": "pact-fixture-source", "t": "vendor"},
    )
    return int(row.scalar_one())


async def _ensure_full_group(
    session: AsyncSession,
    *,
    name: str,
    mitre_id: str,
    aka: list[str],
    description: str,
) -> int:
    """Upsert a group with every pact-required field populated.

    Returns the group's id. Existing rows are NOT mutated — the
    caller gets the first row that matched the name. This makes the
    helper safe to call repeatedly across state setups.
    """
    existing = (
        await session.execute(
            text("SELECT id FROM groups WHERE name = :n"),
            {"n": name},
        )
    ).first()
    if existing is not None:
        return int(existing[0])
    row = await session.execute(
        text(
            "INSERT INTO groups (name, mitre_intrusion_set_id, aka, description) "
            "VALUES (:n, :m, :aka, :d) "
            "RETURNING id"
        ),
        {"n": name, "m": mitre_id, "aka": aka, "d": description},
    )
    return int(row.scalar_one())


async def _ensure_codename(
    session: AsyncSession, *, name: str, group_id: int
) -> int:
    """Upsert a codename linked to a group. Returns its id."""
    existing = (
        await session.execute(
            text("SELECT id FROM codenames WHERE name = :n"),
            {"n": name},
        )
    ).first()
    if existing is not None:
        return int(existing[0])
    row = await session.execute(
        text(
            "INSERT INTO codenames (name, group_id) VALUES (:n, :g) "
            "RETURNING id"
        ),
        {"n": name, "g": group_id},
    )
    return int(row.scalar_one())


async def _ensure_report_with_codename_link(
    session: AsyncSession,
    *,
    source_id: int,
    codename_id: int,
    url_canonical: str,
    title: str,
    published: date,
) -> int:
    """Upsert a reports row + the report_codenames FK row so the
    dashboard aggregator's ``reports → report_codenames → codenames
    → groups`` chain surfaces a non-empty ``top_groups``.

    Returns the report id.
    """
    existing = (
        await session.execute(
            text("SELECT id FROM reports WHERE url_canonical = :u"),
            {"u": url_canonical},
        )
    ).first()
    if existing is not None:
        report_id = int(existing[0])
    else:
        row = await session.execute(
            text(
                "INSERT INTO reports "
                "(source_id, title, url, url_canonical, sha256_title, published) "
                "VALUES (:s, :t, :u, :uc, :sh, :p) "
                "RETURNING id"
            ),
            {
                "s": source_id,
                "t": title,
                "u": url_canonical,
                "uc": url_canonical,
                "sh": f"pact-sha-{url_canonical[-24:]}",
                "p": published,
            },
        )
        report_id = int(row.scalar_one())

    await session.execute(
        text(
            "INSERT INTO report_codenames (report_id, codename_id) "
            "VALUES (:r, :c) ON CONFLICT DO NOTHING"
        ),
        {"r": report_id, "c": codename_id},
    )
    return report_id


async def _ensure_incident_with_motivation(
    session: AsyncSession,
    *,
    title: str,
    motivation: str,
) -> int:
    """Upsert an incidents row + incident_motivations row."""
    existing = (
        await session.execute(
            text("SELECT id FROM incidents WHERE title = :t"),
            {"t": title},
        )
    ).first()
    if existing is not None:
        incident_id = int(existing[0])
    else:
        row = await session.execute(
            text(
                "INSERT INTO incidents (reported, title, description) "
                "VALUES (:r, :t, :d) "
                "RETURNING id"
            ),
            {
                # Inside the pact dashboard filter window
                # (date_from=2026-01-01, date_to=2026-04-18).
                "r": date(2026, 2, 20),
                "t": title,
                "d": "Pact fixture incident",
            },
        )
        incident_id = int(row.scalar_one())
    await session.execute(
        text(
            "INSERT INTO incident_motivations (incident_id, motivation) "
            "VALUES (:i, :m) ON CONFLICT DO NOTHING"
        ),
        {"i": incident_id, "m": motivation},
    )
    return incident_id


async def _ensure_canonical_lazarus_fixture(session: AsyncSession) -> int:
    """Seed the canonical `Lazarus Group` fixture + one linked codename.

    The actors pact interaction happens to use Lazarus-shaped data in
    its matcher example, but matchers accept any row with the right
    SHAPE. Using the named fixture here keeps the seed readable and
    matches the FE list-render example verbatim, so human review of a
    failing verifier log can spot the row quickly.
    """
    group_id = await _ensure_full_group(
        session,
        name="Lazarus Group",
        mitre_id="G0032",
        aka=["APT38", "Hidden Cobra"],
        description="DPRK-attributed cyber espionage and financially motivated group",
    )
    await _ensure_codename(session, name="Andariel", group_id=group_id)
    return group_id


async def _ensure_min_actors(session: AsyncSession, minimum: int) -> None:
    """Ensure the groups table has at least ``minimum`` fully-fleshed
    rows — each with mitre_intrusion_set_id, non-empty aka, non-null
    description, AND at least one linked codename.

    The /actors page-2 pact interaction (offset=50) requires EVERY
    row on page 2 to satisfy the matchers, so filler groups cannot
    be skeletal — they need the same field shape as the canonical
    Lazarus row.

    Idempotent: counts existing groups and tops up the difference.
    """
    count_row = (
        await session.execute(text("SELECT COUNT(*) FROM groups"))
    ).scalar_one()
    existing = int(count_row)
    for i in range(existing, minimum):
        name = f"pact-fixture-group-{i:04d}"
        group_id = await _ensure_full_group(
            session,
            name=name,
            mitre_id=f"G9{i:04d}",
            aka=[f"pact-alias-{i:04d}"],
            description=f"Pact fixture actor {i:04d}",
        )
        await _ensure_codename(
            session,
            name=f"pact-codename-{i:04d}",
            group_id=group_id,
        )


async def _ensure_dashboard_fixture(session: AsyncSession) -> None:
    """Seed the full fixture set the /dashboard/summary pact requires.

    - 1 source (FK for reports)
    - 1 group + 1 codename (for top_groups join chain)
    - 1 report linked to source + codename (populates reports_by_year
      AND completes the report → codename → group chain for
      top_groups)
    - 1 incident + 1 motivation (populates incidents_by_motivation)
    """
    await _ensure_canonical_lazarus_fixture(session)
    source_id = await _ensure_source(session)
    lazarus_id = (
        await session.execute(
            text("SELECT id FROM groups WHERE name = :n"),
            {"n": "Lazarus Group"},
        )
    ).scalar_one()
    andariel_id = (
        await session.execute(
            text("SELECT id FROM codenames WHERE name = :n"),
            {"n": "Andariel"},
        )
    ).scalar_one()
    # Dodge an unused-var warning while still documenting the join.
    _ = lazarus_id
    # Dates land inside the pact's date_from/date_to filter
    # (2026-01-01 to 2026-04-18). Earlier dates would pass the DB
    # seed check but produce empty reports_by_year /
    # incidents_by_motivation arrays under that filter, which would
    # fail the pact's eachLike matcher at verification time.
    await _ensure_report_with_codename_link(
        session,
        source_id=source_id,
        codename_id=int(andariel_id),
        url_canonical="https://pact.test/reports/lazarus-q1",
        title="Pact fixture — Lazarus Group Q1 report",
        published=date(2026, 3, 15),
    )
    await _ensure_incident_with_motivation(
        session,
        title="Pact fixture — Ronin bridge exploit",
        motivation="financial",
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("", include_in_schema=False)
async def provider_states(
    payload: _ProviderStatePayload,
    response: Response,
    session_store: Annotated[SessionStore, Depends(get_session_store)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Handle a single provider-state setup request.

    The verifier calls this synchronously before each interaction.
    Mapping below matches the ``.given(...)`` strings in
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
            await _ensure_canonical_lazarus_fixture(session)
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        if state == "seeded actors with at least 100 rows and an authenticated session":
            # Canonical row first so human reviewers see Lazarus in
            # the verifier log; then fill to 100 with fully-fleshed
            # filler rows so page-2 (offset=50) matchers also hold.
            await _ensure_canonical_lazarus_fixture(session)
            await _ensure_min_actors(session, 100)
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        if state == (
            "seeded reports/incidents/actors and an authenticated analyst session"
        ):
            await _ensure_dashboard_fixture(session)
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        # Unknown state — fall through with a session so the
        # interaction still authenticates. Better to mint a cookie
        # than to silently fail the verifier on a state rename.

    return {"status": "ok"}
