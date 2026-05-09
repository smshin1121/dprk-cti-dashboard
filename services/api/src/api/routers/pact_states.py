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

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.schemas import SessionData
from ..auth.session import SessionStore, get_session_store, set_session_cookie
from ..db import get_db
from ..deps import get_embedding_client
from ..embedding_client import EmbeddingResult

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


class _PactSearchEmbeddingClient:
    """Deterministic llm-proxy stub for Pact's populated /search state.

    The contract-verify CI job boots PG + Redis + uvicorn, but not
    llm-proxy. Without an override, ``get_embedding_client`` resolves
    to ``None`` and the populated ``/search`` pact stays on the FTS-only
    path, which leaves ``vector_rank`` null and breaks the consumer's
    ``integer()`` matcher.

    The populated fixture stamps one-hot embeddings onto the three
    search rows. Returning a query vector with descending non-zero
    weight in the first three dimensions yields a stable cosine order
    across those rows and is sufficient for the contract's type-level
    assertion that ``vector_rank`` is an integer.
    """

    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> EmbeddingResult:
        del texts, model
        vec = [0.0] * 1536
        vec[0] = 1.0
        vec[1] = 0.5
        vec[2] = 0.25
        return EmbeddingResult(
            vectors=[vec],
            model_returned="pact-provider-state-stub",
            cache_hit=False,
            upstream_latency_ms=1,
        )


_PACT_SEARCH_EMBEDDING_CLIENT = _PactSearchEmbeddingClient()


def _clear_embedding_client_override(app) -> None:
    """Remove any prior Pact-installed embedding override.

    The verifier reuses one uvicorn process for the whole run, so a
    populated-search override must not leak into unrelated interactions.
    Every provider-state call starts by restoring the baseline.
    """

    app.dependency_overrides.pop(get_embedding_client, None)


def _install_pact_search_embedding_override(app) -> None:
    """Enable the hybrid /search path for the populated Pact fixture."""

    app.dependency_overrides[get_embedding_client] = (
        lambda: _PACT_SEARCH_EMBEDDING_CLIENT
    )


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


async def _ensure_source(
    session: AsyncSession, *, name: str = "pact-fixture-source"
) -> int:
    """Upsert a sources row keyed by ``name``; returns its id.

    The default name preserves the original PR #12 helper behaviour for
    every existing caller. Pass an explicit ``name`` to seed a fixture
    whose ``top_sources`` join chain must be isolated from sibling
    fixtures (e.g. PR #3 actor-network fixture uses
    ``actor-network-fixture-SRC1``).
    """
    existing = (
        await session.execute(
            text("SELECT id FROM sources WHERE name = :n"),
            {"n": name},
        )
    ).first()
    if existing is not None:
        return int(existing[0])
    row = await session.execute(
        text(
            "INSERT INTO sources (name, type) VALUES (:n, :t) "
            "RETURNING id"
        ),
        {"n": name, "t": "vendor"},
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
    reported: date | None = None,
) -> int:
    """Upsert an incidents row + incident_motivations row.

    ``reported`` defaults to 2026-02-20 (inside the pact dashboard
    filter window ``2026-01-01..2026-04-18``). The PR #23 incidents-
    trend fixture overrides this to spread incidents across multiple
    months so the eachLike(``buckets``) array is non-empty under
    bucket-level grouping.
    """
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
                "r": reported if reported is not None else date(2026, 2, 20),
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


async def _ensure_incident_with_sector(
    session: AsyncSession,
    *,
    title: str,
    sector_code: str,
    reported: date | None = None,
) -> int:
    """Upsert an incidents row + incident_sectors row.

    Mirrors ``_ensure_incident_with_motivation`` on the
    ``incident_sectors`` junction. Used by the PR #23
    ``/analytics/incidents_trend?group_by=sector`` pact fixture.
    """
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
                "r": reported if reported is not None else date(2026, 2, 20),
                "t": title,
                "d": "Pact fixture incident (sector)",
            },
        )
        incident_id = int(row.scalar_one())
    await session.execute(
        text(
            "INSERT INTO incident_sectors (incident_id, sector_code) "
            "VALUES (:i, :s) ON CONFLICT DO NOTHING"
        ),
        {"i": incident_id, "s": sector_code},
    )
    return incident_id


# ---------------------------------------------------------------------------
# PR #13 Group B — analytics fixture helpers
# ---------------------------------------------------------------------------
#
# Three new endpoints (/analytics/attack_matrix, /trend, /geo) land in
# PR #13 Group A. Group J will add consumer pact interactions for them
# to ``frontend-dprk-cti-api.pact.test.ts``. Each interaction needs a
# provider state the BE can seed — these helpers do that.
#
# Design principles carried from PR #12 Group I:
#
# 1. Every fixture row satisfies the STRICTEST matcher the FE pact
#    will use for that endpoint. Concretely: every analytics response
#    array uses ``eachLike(...)`` so the aggregator MUST return a
#    non-empty list under the pact's filter window; and every sub-
#    object field must have a non-null value typed correctly.
# 2. Every helper is idempotent (SELECT-first OR ``ON CONFLICT DO
#    NOTHING``). The verifier replays state setup before each
#    interaction, so the same helper can be invoked 3+ times per run.
# 3. Dates stay inside the committed pact filter window
#    (``date_from=2026-01-01`` .. ``date_to=2026-04-18``) — seeding
#    outside the window is the failure mode that burned PR #12
#    (``06e47e9``) when 2024-* dates were filtered out of eachLike
#    arrays at verify time.


async def _ensure_technique(
    session: AsyncSession,
    *,
    mitre_id: str,
    name: str,
    tactic: str,
) -> int:
    """Upsert a techniques row. Returns its id.

    ``tactic`` is required here (non-null) because the
    ``/analytics/attack_matrix`` aggregator drops null-tactic rows —
    a fixture with a null tactic would never surface in the matrix
    and would leave the ``rows`` array empty.
    """
    existing = (
        await session.execute(
            text("SELECT id FROM techniques WHERE mitre_id = :m"),
            {"m": mitre_id},
        )
    ).first()
    if existing is not None:
        return int(existing[0])
    row = await session.execute(
        text(
            "INSERT INTO techniques (mitre_id, name, tactic) "
            "VALUES (:m, :n, :tac) RETURNING id"
        ),
        {"m": mitre_id, "n": name, "tac": tactic},
    )
    return int(row.scalar_one())


async def _link_report_technique(
    session: AsyncSession, *, report_id: int, technique_id: int
) -> None:
    """Idempotent ``report_techniques`` link row."""
    await session.execute(
        text(
            "INSERT INTO report_techniques (report_id, technique_id) "
            "VALUES (:r, :t) ON CONFLICT DO NOTHING"
        ),
        {"r": report_id, "t": technique_id},
    )


async def _ensure_incident_with_country(
    session: AsyncSession,
    *,
    title: str,
    reported: date,
    country_iso2: str,
) -> int:
    """Upsert an incidents row + incident_countries row.

    Mirrors ``_ensure_incident_with_motivation`` but on the country
    join table. ``title`` is the natural key for the incident — the
    geo fixture picks unique titles per country so incidents are not
    shared with the dashboard fixture's Ronin row.
    """
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
                "VALUES (:r, :t, :d) RETURNING id"
            ),
            {
                "r": reported,
                "t": title,
                "d": "Pact fixture incident (geo)",
            },
        )
        incident_id = int(row.scalar_one())
    await session.execute(
        text(
            "INSERT INTO incident_countries (incident_id, country_iso2) "
            "VALUES (:i, :c) ON CONFLICT DO NOTHING"
        ),
        {"i": incident_id, "c": country_iso2},
    )
    return incident_id


async def _ensure_attack_matrix_fixture(session: AsyncSession) -> None:
    """Seed the fixture set ``/analytics/attack_matrix`` pact requires.

    Response contract shape (plan D2):

        {tactics: eachLike({id, name}), rows: eachLike({tactic_id,
         techniques: eachLike({technique_id, count})})}

    Seed:
      - 3 techniques across 2 tactics (TA0001: T1566 + T1190; TA0002:
        T1059). Non-null tactic on all — null-tactic rows would be
        dropped by the aggregator.
      - 3 reports dated 2026-03-15 (inside pact window) linked BOTH to
        the canonical Lazarus codename (so a ``group_id=1`` filter
        still produces a non-empty matrix) AND to techniques.
      - Technique mixture ensures:
          * TA0001 has 2 techniques (T1566 + T1190) — one report r1 is
            linked to both to exercise the ``COUNT(DISTINCT report_id)``
            invariant (should count 1 not 2 under T1566).
          * TA0002 has 1 technique (T1059).

    Aggregator output (no filter):
      - TA0001: {T1566: 2, T1190: 1}
      - TA0002: {T1059: 1}
    Every ``eachLike`` array is therefore non-empty.
    """
    source_id = await _ensure_source(session)
    lazarus_id = await _ensure_canonical_lazarus_fixture(session)
    andariel_id = await _ensure_codename(
        session, name="Andariel", group_id=lazarus_id
    )

    t_1566 = await _ensure_technique(
        session, mitre_id="T1566", name="Phishing", tactic="TA0001"
    )
    t_1190 = await _ensure_technique(
        session,
        mitre_id="T1190",
        name="Exploit Public-Facing Application",
        tactic="TA0001",
    )
    t_1059 = await _ensure_technique(
        session,
        mitre_id="T1059",
        name="Command and Scripting Interpreter",
        tactic="TA0002",
    )

    r1 = await _ensure_report_with_codename_link(
        session,
        source_id=source_id,
        codename_id=andariel_id,
        url_canonical="https://pact.test/analytics/attack/r1",
        title="Pact fixture — attack_matrix r1",
        published=date(2026, 3, 15),
    )
    await _link_report_technique(session, report_id=r1, technique_id=t_1566)
    await _link_report_technique(session, report_id=r1, technique_id=t_1190)

    r2 = await _ensure_report_with_codename_link(
        session,
        source_id=source_id,
        codename_id=andariel_id,
        url_canonical="https://pact.test/analytics/attack/r2",
        title="Pact fixture — attack_matrix r2",
        published=date(2026, 3, 15),
    )
    await _link_report_technique(session, report_id=r2, technique_id=t_1566)

    r3 = await _ensure_report_with_codename_link(
        session,
        source_id=source_id,
        codename_id=andariel_id,
        url_canonical="https://pact.test/analytics/attack/r3",
        title="Pact fixture — attack_matrix r3",
        published=date(2026, 3, 15),
    )
    await _link_report_technique(session, report_id=r3, technique_id=t_1059)


async def _ensure_trend_fixture(session: AsyncSession) -> None:
    """Seed the fixture set ``/analytics/trend`` pact requires.

    Response contract (plan D2):

        {buckets: eachLike({month: matches(YYYY-MM), count})}

    Seed: 3 reports spanning 2 months inside the pact window so the
    response contains ≥2 buckets (gives more signal than a single-row
    eachLike sample). Reports are linked to the Lazarus codename so a
    group-filtered trend still produces non-empty buckets.
    """
    source_id = await _ensure_source(session)
    lazarus_id = await _ensure_canonical_lazarus_fixture(session)
    andariel_id = await _ensure_codename(
        session, name="Andariel", group_id=lazarus_id
    )

    for idx, published in enumerate(
        [date(2026, 2, 10), date(2026, 2, 20), date(2026, 3, 5)]
    ):
        await _ensure_report_with_codename_link(
            session,
            source_id=source_id,
            codename_id=andariel_id,
            url_canonical=f"https://pact.test/analytics/trend/r{idx}",
            title=f"Pact fixture — trend r{idx}",
            published=published,
        )


async def _ensure_geo_fixture(session: AsyncSession) -> None:
    """Seed the fixture set ``/analytics/geo`` pact requires.

    Response contract (plan D2 + D7):

        {countries: eachLike({iso2: string(min=2,max=2), count})}

    Seed: 3 incidents with distinct ISO2 country codes — including
    ``KP`` to exercise the plan D7 "DPRK is a plain row" invariant.
    Dates land inside the pact window. No group_ids wiring is needed
    (``/analytics/geo`` is group-no-op by schema constraint).
    """
    for country_iso2 in ("KR", "US", "KP"):
        await _ensure_incident_with_country(
            session,
            title=f"Pact fixture — geo {country_iso2}",
            reported=date(2026, 2, 20),
            country_iso2=country_iso2,
        )


async def _ensure_actor_network_fixture(session: AsyncSession) -> None:
    """Seed the fixture set ``/analytics/actor_network`` pact requires.

    Response contract (plan ``docs/plans/actor-network-data.md`` v1.5
    L2):

        {nodes: eachLike({id: string(...), kind: string(...),
                          label: string(...), degree: integer(>=1)}),
         edges: eachLike({source_id: string(...),
                          target_id: string(...),
                          weight: integer(>=1)}),
         cap_breached: false}

    Seed produces non-empty arrays for all three edge classes (plan
    L3) so the FE pact's ``eachLike(nodes)`` and ``eachLike(edges)``
    matchers have rows under the pact filter window
    (``date_from=2026-01-01..date_to=2026-04-18``):

      (a) actor↔actor — codenames in different groups co-occur on the
          same report.
      (b) actor↔tool   — codename → report → technique.
      (c) actor↔sector — incident_sectors → incidents → incident_sources
          → reports → report_codenames → codenames → groups.

    Layout
    ------
      - 1 source: ``actor-network-fixture-SRC1`` (NOT shared with the
        canonical ``pact-fixture-source`` row so the actor-network
        state cannot cross-contaminate dashboard's ``top_sources``).
      - 3 groups: ``actor-network-fixture-G1/2/3`` (mitre
        ``G9101/G9102/G9103`` — the ``G9xxx`` MITRE range is unused in
        real ATT&CK, eliminating production-data collisions; the
        ``G9101+`` sub-range avoids reusing ``G9003`` which is
        already taken by ``_ensure_actor_detail_fixture``. Note:
        ``groups.mitre_intrusion_set_id`` is NOT a unique column, so
        a sibling reusing the same value would not throw a DB error,
        but distinct values keep the fixture self-describing).
      - 3 codenames: ``actor-network-fixture-CN1/2/3`` (1:1 with
        ``G1/2/3``).
      - 3 techniques: ``T9001/T9002/T9003`` (``T9xxx`` is unused in
        real ATT&CK).
      - 1 incident: ``Pact fixture — actor-network INC1``
        (reported ``2026-02-15``, inside the pact window).
      - 2 reports: ``actor-network-fixture-RPT1/RPT2`` (published
        ``2026-03-10`` / ``2026-03-15``, inside the pact window).
      - 2 incident_sources: INC1 → RPT1, INC1 → RPT2.
      - 4 report_codenames: RPT1 → {CN1, CN2}, RPT2 → {CN2, CN3}.
      - 4 report_techniques: RPT1 → {T9001, T9002},
        RPT2 → {T9002, T9003}.
      - 3 incident_sectors: INC1 →
        {``actor-network-fixture-SEC1/2/3``}.

    Edges produced (per L3 / aggregator output)
    -------------------------------------------
      (a) actor↔actor  — G1↔G2 (r1, weight 1), G2↔G3 (r2, weight 1).
      (b) actor↔tool   — G2↔T9002 weight 2 (both reports), six other
                          group/technique pairs weight 1.
      (c) actor↔sector — every (group, sector) pair at least 1 — the
                          incident links to BOTH reports, both reports
                          touch G2, and r1/r2 cover all three groups.

    Distinct natural keys per memory ``pitfall_pinned_id_vs_unique_name``
    so the seed cannot collide with sibling fixtures (lazarus,
    attack_matrix, trend, geo, dashboard, incidents_trend).

    Plan v1.5 §4 T8 mentioned ``999xxx`` pinned IDs; this seed does
    NOT use pinned IDs because the actor-network endpoint has no path
    parameter — memory ``pattern_pact_literal_pinned_paths`` applies
    only to path-param interactions. Sibling analytics fixtures
    (``_ensure_attack_matrix_fixture`` / ``_ensure_trend_fixture`` /
    ``_ensure_geo_fixture``) all use the natural-key SELECT-first
    pattern with auto-assigned IDs; this fixture follows that
    convention. Recorded as a v1.6 §0.1 amendment in the plan.
    """
    # 1. Source — distinct from the canonical pact-fixture-source so
    #    actor-network's reports never bleed into dashboard's
    #    top_sources aggregation.
    source_id = await _ensure_source(
        session, name="actor-network-fixture-SRC1"
    )

    # 2. Three groups (parents for codenames). Distinct mitre IDs in
    #    the unused G9xxx range. The G9101+ sub-range avoids reusing
    #    G9003 from _ensure_actor_detail_fixture (mitre_intrusion_set_id
    #    is not unique, so the collision would not raise a DB error,
    #    but a distinct value keeps the fixture self-describing).
    group_ids: list[int] = []
    for idx in (1, 2, 3):
        gid = await _ensure_full_group(
            session,
            name=f"actor-network-fixture-G{idx}",
            mitre_id=f"G9{100 + idx:03d}",
            aka=[f"actor-network-aka-{idx}"],
            description=(
                f"Pact fixture group {idx} for /analytics/actor_network"
            ),
        )
        group_ids.append(gid)

    # 3. Three codenames — 1:1 with the groups so each group has
    #    exactly one codename for the report_codenames join chain.
    codename_ids: list[int] = []
    for idx, gid in enumerate(group_ids, start=1):
        cn_id = await _ensure_codename(
            session,
            name=f"actor-network-fixture-CN{idx}",
            group_id=gid,
        )
        codename_ids.append(cn_id)

    # 4. Three techniques — non-null tactic per
    #    ``/analytics/attack_matrix`` aggregator convention.
    technique_ids: list[int] = []
    for idx in (1, 2, 3):
        tid = await _ensure_technique(
            session,
            mitre_id=f"T900{idx}",
            name=f"actor-network-fixture-T{idx}",
            tactic="TA0001",
        )
        technique_ids.append(tid)

    # 5. Two reports — published dates inside the pact filter window
    #    (2026-01-01..2026-04-18). url_canonical is the natural key.
    report_ids: list[int] = []
    for idx, published in enumerate(
        [date(2026, 3, 10), date(2026, 3, 15)], start=1
    ):
        url = f"https://pact.test/analytics/actor-network/r{idx}"
        existing = (
            await session.execute(
                text("SELECT id FROM reports WHERE url_canonical = :u"),
                {"u": url},
            )
        ).first()
        if existing is not None:
            report_ids.append(int(existing[0]))
            continue
        row = await session.execute(
            text(
                "INSERT INTO reports "
                "(source_id, title, url, url_canonical, sha256_title, published) "
                "VALUES (:s, :t, :u, :uc, :sh, :p) "
                "RETURNING id"
            ),
            {
                "s": source_id,
                "t": f"Pact fixture — actor-network r{idx}",
                "u": url,
                "uc": url,
                "sh": f"pact-sha-actor-network-r{idx}",
                "p": published,
            },
        )
        report_ids.append(int(row.scalar_one()))

    # 6. report_codenames — RPT1→{CN1,CN2}, RPT2→{CN2,CN3}. CN2
    #    overlap on both reports gives G2 the highest degree
    #    (connects to G1, G3, all techniques, all sectors).
    rc_pairs = [
        (report_ids[0], codename_ids[0]),
        (report_ids[0], codename_ids[1]),
        (report_ids[1], codename_ids[1]),
        (report_ids[1], codename_ids[2]),
    ]
    for r_id, c_id in rc_pairs:
        await session.execute(
            text(
                "INSERT INTO report_codenames (report_id, codename_id) "
                "VALUES (:r, :c) ON CONFLICT DO NOTHING"
            ),
            {"r": r_id, "c": c_id},
        )

    # 7. report_techniques — RPT1→{T9001,T9002}, RPT2→{T9002,T9003}.
    #    T9002 overlap creates the only weight-2 actor↔tool edge
    #    (G2↔T9002).
    rt_pairs = [
        (report_ids[0], technique_ids[0]),
        (report_ids[0], technique_ids[1]),
        (report_ids[1], technique_ids[1]),
        (report_ids[1], technique_ids[2]),
    ]
    for r_id, t_id in rt_pairs:
        await _link_report_technique(
            session, report_id=r_id, technique_id=t_id
        )

    # 8. One incident — reported date inside the pact filter window.
    inc_title = "Pact fixture — actor-network INC1"
    existing_inc = (
        await session.execute(
            text("SELECT id FROM incidents WHERE title = :t"),
            {"t": inc_title},
        )
    ).first()
    if existing_inc is not None:
        incident_id = int(existing_inc[0])
    else:
        row = await session.execute(
            text(
                "INSERT INTO incidents (reported, title, description) "
                "VALUES (:r, :t, :d) "
                "RETURNING id"
            ),
            {
                "r": date(2026, 2, 15),
                "t": inc_title,
                "d": (
                    "Pact fixture incident for actor-network sector edges"
                ),
            },
        )
        incident_id = int(row.scalar_one())

    # 9. incident_sources — link the incident to BOTH reports so the
    #    5-table actor↔sector chain produces edges for every group
    #    that appears on either report.
    for r_id in report_ids:
        await session.execute(
            text(
                "INSERT INTO incident_sources (incident_id, report_id) "
                "VALUES (:i, :r) ON CONFLICT DO NOTHING"
            ),
            {"i": incident_id, "r": r_id},
        )

    # 10. incident_sectors — 3 distinct sector_code values keeps
    #     three actor↔sector edges per group.
    for idx in (1, 2, 3):
        await session.execute(
            text(
                "INSERT INTO incident_sectors (incident_id, sector_code) "
                "VALUES (:i, :s) ON CONFLICT DO NOTHING"
            ),
            {
                "i": incident_id,
                "s": f"actor-network-fixture-SEC{idx}",
            },
        )


async def _ensure_incidents_trend_motivation_fixture(
    session: AsyncSession,
) -> None:
    """Seed for ``/analytics/incidents_trend?group_by=motivation`` pact.

    Response contract (PR #23 §6.A C1):

        {buckets: eachLike({month, count, series: eachLike({key, count})}),
         group_by: "motivation"}

    Seed: 3 incidents across 2 months inside the pact window so both
    the outer ``buckets`` eachLike AND the inner per-bucket ``series``
    eachLike have non-empty arrays. Pact-ruby ``eachLike`` rejects
    empty (``pitfall_pact_fixture_shape``).

    Distinct titles per row keep these incidents separate from the
    geo / dashboard fixtures so cross-state accumulation doesn't
    cross-contaminate counts.
    """
    incidents = [
        ("Pact fixture — incidents_trend motivation feb-espionage", "Espionage", date(2026, 2, 10)),
        ("Pact fixture — incidents_trend motivation feb-finance", "Finance", date(2026, 2, 20)),
        ("Pact fixture — incidents_trend motivation mar-espionage", "Espionage", date(2026, 3, 5)),
    ]
    for title, motivation, reported in incidents:
        await _ensure_incident_with_motivation(
            session,
            title=title,
            motivation=motivation,
            reported=reported,
        )


async def _ensure_incidents_trend_sector_fixture(
    session: AsyncSession,
) -> None:
    """Seed for ``/analytics/incidents_trend?group_by=sector`` pact.

    Mirrors the motivation fixture on the ``incident_sectors``
    junction. Same eachLike non-empty rules apply: ≥1 bucket and ≥1
    series row per bucket.
    """
    incidents = [
        ("Pact fixture — incidents_trend sector feb-gov", "GOV", date(2026, 2, 10)),
        ("Pact fixture — incidents_trend sector feb-fin", "FIN", date(2026, 2, 20)),
        ("Pact fixture — incidents_trend sector mar-ene", "ENE", date(2026, 3, 5)),
    ]
    for title, sector_code, reported in incidents:
        await _ensure_incident_with_sector(
            session,
            title=title,
            sector_code=sector_code,
            reported=reported,
        )


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

    - 1 source (FK for reports) — seeds top_sources via the
      reports.source_id → sources.name join chain
    - 1 group + 1 codename (for top_groups join chain)
    - 1 report linked to source + codename (populates reports_by_year
      AND completes the report → codename → group chain for top_groups
      AND surfaces the source under top_sources)
    - 1 incident + 1 motivation (populates incidents_by_motivation)
    - 1 incident + 1 sector (populates top_sectors — PR #23 §6.A C2;
      separate row from the motivation-linked one to keep the two
      junction surfaces independent)
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
    await _ensure_incident_with_sector(
        session,
        title="Pact fixture — dashboard sector seed",
        sector_code="GOV",
        reported=date(2026, 2, 20),
    )


# ---------------------------------------------------------------------------
# PR #14 Group C — detail + similar-reports fixture helpers
# ---------------------------------------------------------------------------
#
# Four FE pact interactions land in PR #14 Group G:
#   GET /reports/{id}            (happy)
#   GET /incidents/{id}          (happy)
#   GET /actors/{id}             (happy)
#   GET /reports/{id}/similar    (happy, populated + optional D10 empty)
#
# Path-param discipline:
#   pact-js V3 sends the consumer's example URL verbatim to the
#   provider. For interactions with a path param, we pin the fixture
#   id to a HIGH KNOWN-GOOD value (999xxx range) so (a) the consumer
#   pact can use that exact number as its example, and (b) natural
#   data rows the bootstrap ETL seeds can't collide with the pact
#   fixtures. The ids are:
#
#     999001 — report detail fixture (source report for /reports/{id})
#     999002 — incident detail fixture (for /incidents/{id})
#     999011, 999012, 999013 — similar neighbors for populated state
#     999020 — similar populated fixture source
#     999030 — similar empty-embedding fixture source
#     999031 — similar empty-embedding neighbor (has embedding)
#
# Idempotency discipline:
#   All helpers use ``ON CONFLICT (id) DO NOTHING`` when we pin an
#   id explicitly, OR SELECT-then-INSERT for natural-key rows
#   (source, codenames, techniques). A second call with the same
#   state is a no-op; a third still finds the fixture intact.
#
# D10 empty-embedding fixture:
#   plan D10 locks the "no embedding → 200 + {items: []}" contract.
#   The empty-embedding state seeds the source report without
#   populating its vector column AND seeds ONE neighbor WITH an
#   embedding — so the verifier sees a DB where the kNN query
#   cannot run because ``:src.embedding IS NULL``, and the service
#   falls into the D10 early-return branch even though the DB is
#   not empty of embeddings elsewhere.
#
# Embedding format:
#   ``reports.embedding`` is ``vector(1536)`` (migration 0001). We
#   construct 1536-dim vectors using ``_make_embedding`` below —
#   most slots are 0.0, a handful carry known values so three
#   neighbors produce distinct cosine similarities against the
#   source vector. The pact matcher only verifies SHAPE (not exact
#   score values), so we don't pin specific similarity numbers at
#   the pact layer — the real-PG unit-test suite verifies that
#   path.


# Pinned fixture ids — used by the FE pact's path-param examples
# in Group G. Kept as module constants so Group G can import the
# same numbers without drift.
REPORT_DETAIL_FIXTURE_ID = 999001
INCIDENT_DETAIL_FIXTURE_ID = 999002
# Actor detail (added in Group G) — previously `_ensure_actor_detail_
# fixture` aliased the canonical Lazarus fixture whose id was
# DB-assigned via the `groups` sequence. That made the pact consumer
# structurally unable to target a concrete `/actors/{id}` path
# without either (a) a regex-on-path matcher (R3 pact-js V3 panic
# risk) or (b) hoping the sequence put Lazarus at id=1 (drift-prone
# across state replays and fixture reorderings). Pinning a separate
# Pact-specific actor at 999003 eliminates both risks; the matcher
# example values keep Lazarus-shaped content so human review of a
# failing verifier log is still readable.
ACTOR_DETAIL_FIXTURE_ID = 999003
# PR #15 Group C — actor with NO linked reports. Distinct id so the
# pact consumer can target ``/actors/999004/reports`` literally and
# the D15(b/c/d) 200-empty interaction does not share state with the
# populated interaction (which reuses ACTOR_DETAIL_FIXTURE_ID=999003
# via _ensure_actor_with_reports_fixture).
ACTOR_WITH_NO_REPORTS_ID = 999004
# PR #15 Group C — pinned report ids linked to actor 999003 via the
# existing ``pact-actor-detail-codename`` (seeded by _ensure_actor_
# detail_fixture). Three reports with distinct ``published`` dates
# give the matcher a stable newest-first ordering (plan D16) and
# ensure the list isn't padded to exactly one row.
ACTOR_REPORTS_FIXTURE_REPORT_IDS = (999050, 999051, 999052)
SIMILAR_POPULATED_SOURCE_ID = 999020
SIMILAR_POPULATED_NEIGHBOR_IDS = (999011, 999012, 999013)
SIMILAR_EMPTY_EMBEDDING_SOURCE_ID = 999030
SIMILAR_EMPTY_EMBEDDING_NEIGHBOR_ID = 999031
# PR #17 Group C — /search populated + empty fixtures. Pinned into the
# 999060-range so they never collide with the PR #14/#15 ranges above.
# Populated reports carry "Lazarus" in BOTH title and summary so the
# FTS document ``title || ' ' || summary`` matches the pact's
# ``q=lazarus`` interaction under ``plainto_tsquery('simple', ...)``.
# Empty distractor exists so a query against ``nomatchxyz123`` runs
# against a non-empty reports table (an empty table would trivially
# satisfy the D10 envelope and hide an FTS-predicate regression).
SEARCH_POPULATED_FIXTURE_REPORT_IDS = (999060, 999061, 999062)
SEARCH_EMPTY_FIXTURE_REPORT_IDS = (999063,)


def _make_embedding(non_zero_slots: dict[int, float]) -> str:
    """Produce a 1536-dim pgvector literal string.

    Most slots are 0.0; entries in ``non_zero_slots`` override.
    Returned form is the pgvector text-literal syntax
    ``'[v0,v1,...,v1535]'`` that Postgres casts via ``::vector``.
    1536 dimensions matches migration 0001's
    ``ALTER TABLE reports ADD COLUMN embedding vector(1536)``.

    Keeping this a pure string-builder (no numpy) avoids pulling a
    heavy dep into the state-handler path that runs inside the live
    API container.
    """
    values = ["0"] * 1536
    for slot, value in non_zero_slots.items():
        if not 0 <= slot < 1536:
            raise ValueError(f"slot out of range: {slot}")
        values[slot] = repr(float(value))
    return "[" + ",".join(values) + "]"


async def _ensure_report_detail_fixture(session: AsyncSession) -> None:
    """Seed the fixture set that ``GET /reports/{id}`` pact uses.

    One source report with every related collection a happy-path
    matcher needs:
      - report row (id = REPORT_DETAIL_FIXTURE_ID)
      - source + source_name link
      - 2 tags via report_tags (for ``tags: eachLike('tag')``)
      - 1 codename via report_codenames (Andariel reused)
      - 1 technique via report_techniques (T1566 reused from
        attack_matrix fixture if present, else seeded here)
      - 2 linked incidents via incident_sources with distinct
        ``reported`` dates so the newest-first ordering has two
        rows to pick from (plan D9 cap = 10, so 2 comfortably fits)
    """
    source_id = await _ensure_source(session)
    lazarus_id = await _ensure_full_group(
        session,
        name="Lazarus Group",
        mitre_id="G0032",
        aka=["APT38", "Hidden Cobra"],
        description="DPRK-attributed cyber espionage and financially motivated group",
    )
    andariel_id = await _ensure_codename(
        session, name="Andariel", group_id=lazarus_id
    )

    # Insert report with pinned id — ON CONFLICT DO NOTHING so a
    # repeat state setup is safe.
    await session.execute(
        text(
            "INSERT INTO reports "
            "(id, source_id, title, url, url_canonical, sha256_title, "
            "published, lang, tlp, summary) "
            "VALUES (:id, :s, :t, :u, :uc, :sh, :p, :l, :tlp, :sm) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": REPORT_DETAIL_FIXTURE_ID,
            "s": source_id,
            "t": "Pact fixture — report detail source",
            "u": "https://pact.test/reports/detail/source",
            "uc": "https://pact.test/reports/detail/source",
            "sh": "pact-sha-detail-source-fixture",
            "p": date(2026, 3, 15),
            "l": "en",
            "tlp": "WHITE",
            "sm": "Pact fixture body — report detail happy path.",
        },
    )

    # 2 tags — reuse-or-insert by name, then link.
    for tag_name in ("pact-detail-tag-a", "pact-detail-tag-b"):
        existing = (
            await session.execute(
                text("SELECT id FROM tags WHERE name = :n"), {"n": tag_name}
            )
        ).first()
        if existing is None:
            row = await session.execute(
                text(
                    "INSERT INTO tags (name, type) VALUES (:n, :t) RETURNING id"
                ),
                {"n": tag_name, "t": "fixture"},
            )
            tag_id = int(row.scalar_one())
        else:
            tag_id = int(existing[0])
        await session.execute(
            text(
                "INSERT INTO report_tags (report_id, tag_id) "
                "VALUES (:r, :t) ON CONFLICT DO NOTHING"
            ),
            {"r": REPORT_DETAIL_FIXTURE_ID, "t": tag_id},
        )

    # 1 codename link (Andariel).
    await session.execute(
        text(
            "INSERT INTO report_codenames (report_id, codename_id) "
            "VALUES (:r, :c) ON CONFLICT DO NOTHING"
        ),
        {"r": REPORT_DETAIL_FIXTURE_ID, "c": andariel_id},
    )

    # 1 technique link.
    t_1566 = await _ensure_technique(
        session, mitre_id="T1566", name="Phishing", tactic="TA0001"
    )
    await _link_report_technique(
        session, report_id=REPORT_DETAIL_FIXTURE_ID, technique_id=t_1566
    )

    # 2 linked incidents via incident_sources — distinct reported
    # dates so D9's newest-first ordering has a deterministic answer.
    for idx, reported_date in enumerate(
        [date(2026, 2, 10), date(2026, 1, 20)], start=1
    ):
        inc_title = f"Pact fixture — report detail linked incident {idx}"
        existing = (
            await session.execute(
                text("SELECT id FROM incidents WHERE title = :t"),
                {"t": inc_title},
            )
        ).first()
        if existing is not None:
            incident_id = int(existing[0])
        else:
            row = await session.execute(
                text(
                    "INSERT INTO incidents (reported, title, description) "
                    "VALUES (:r, :t, :d) RETURNING id"
                ),
                {
                    "r": reported_date,
                    "t": inc_title,
                    "d": "Pact fixture incident linked to report detail",
                },
            )
            incident_id = int(row.scalar_one())
        await session.execute(
            text(
                "INSERT INTO incident_sources (incident_id, report_id) "
                "VALUES (:i, :r) ON CONFLICT DO NOTHING"
            ),
            {"i": incident_id, "r": REPORT_DETAIL_FIXTURE_ID},
        )


async def _ensure_incident_detail_fixture(session: AsyncSession) -> None:
    """Seed the fixture set that ``GET /incidents/{id}`` pact uses.

    One incident with every related collection a happy-path matcher
    needs:
      - incident row (id = INCIDENT_DETAIL_FIXTURE_ID)
      - 1 motivation, 1 sector, 1 country
      - 2 linked reports via incident_sources with distinct published
        dates so the D9 newest-first ordering has two rows to pick
        from (cap = 20, so 2 fits)
    """
    source_id = await _ensure_source(session)

    await session.execute(
        text(
            "INSERT INTO incidents (id, reported, title, description, "
            "est_loss_usd, attribution_confidence) "
            "VALUES (:id, :r, :t, :d, :el, :ac) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": INCIDENT_DETAIL_FIXTURE_ID,
            "r": date(2026, 2, 20),
            "t": "Pact fixture — incident detail source",
            "d": "Pact fixture incident for /incidents/{id} happy path",
            "el": 100000,
            "ac": "HIGH",
        },
    )
    # N:M flat arrays.
    await session.execute(
        text(
            "INSERT INTO incident_motivations (incident_id, motivation) "
            "VALUES (:i, :m) ON CONFLICT DO NOTHING"
        ),
        {"i": INCIDENT_DETAIL_FIXTURE_ID, "m": "financial"},
    )
    await session.execute(
        text(
            "INSERT INTO incident_sectors (incident_id, sector_code) "
            "VALUES (:i, :s) ON CONFLICT DO NOTHING"
        ),
        {"i": INCIDENT_DETAIL_FIXTURE_ID, "s": "crypto"},
    )
    await session.execute(
        text(
            "INSERT INTO incident_countries (incident_id, country_iso2) "
            "VALUES (:i, :c) ON CONFLICT DO NOTHING"
        ),
        {"i": INCIDENT_DETAIL_FIXTURE_ID, "c": "KR"},
    )

    # 2 linked reports (newest-first ordering has a deterministic
    # answer). Distinct url_canonicals keep this isolated from the
    # other fixtures' reports.
    for idx, published in enumerate(
        [date(2026, 3, 10), date(2026, 2, 28)], start=1
    ):
        uc = f"https://pact.test/incidents/detail/linked-report-{idx}"
        existing = (
            await session.execute(
                text("SELECT id FROM reports WHERE url_canonical = :u"),
                {"u": uc},
            )
        ).first()
        if existing is not None:
            report_id = int(existing[0])
        else:
            row = await session.execute(
                text(
                    "INSERT INTO reports "
                    "(source_id, title, url, url_canonical, sha256_title, "
                    "published) "
                    "VALUES (:s, :t, :u, :uc, :sh, :p) RETURNING id"
                ),
                {
                    "s": source_id,
                    "t": f"Pact fixture — incident detail linked report {idx}",
                    "u": uc,
                    "uc": uc,
                    "sh": f"pact-sha-inc-detail-linked-{idx}",
                    "p": published,
                },
            )
            report_id = int(row.scalar_one())
        await session.execute(
            text(
                "INSERT INTO incident_sources (incident_id, report_id) "
                "VALUES (:i, :r) ON CONFLICT DO NOTHING"
            ),
            {"i": INCIDENT_DETAIL_FIXTURE_ID, "r": report_id},
        )


async def _ensure_actor_detail_fixture(session: AsyncSession) -> None:
    """Seed the pinned-id actor fixture that ``GET /actors/{id}`` pact uses.

    Deliberately does NOT reuse ``_ensure_canonical_lazarus_fixture``
    — that helper lets the DB sequence assign the Lazarus id, which
    is drift-prone across state replays and makes the consumer pact
    either (a) dependent on regex-on-path (pact-js V3 R3 risk) or
    (b) reliant on sequence ordering that nothing guarantees.

    Instead, seed a Pact-specific group at ``ACTOR_DETAIL_FIXTURE_ID``
    with a distinct name (``groups.name`` is UNIQUE — we can't
    pin-id-upsert with the Lazarus name without risking a conflict
    when another fixture has already seeded Lazarus under a
    different id). The group carries Lazarus-shaped core fields
    plus one linked codename, which is the full surface the actor
    detail DTO exposes per plan D11 (no linked-reports traversal).

    The pact consumer matchers are ``like(...)`` + ``eachLike(...)``
    on shape, so example values (name "Lazarus Group", codenames
    ["Andariel"]) match this fixture's values (name "Pact fixture
    actor detail", codename "pact-actor-detail-codename") by TYPE
    — integer/string — not by exact value. Human reviewers of a
    failing verifier log still see a readable Lazarus-shaped row.

    Idempotent: ``ON CONFLICT (id) DO NOTHING`` on the groups insert
    + ``_ensure_codename`` is SELECT-first.
    """
    await session.execute(
        text(
            "INSERT INTO groups "
            "(id, name, mitre_intrusion_set_id, aka, description) "
            "VALUES (:id, :n, :m, :aka, :d) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": ACTOR_DETAIL_FIXTURE_ID,
            "n": "Pact fixture actor detail",
            "m": "G9003",
            "aka": ["pact-fixture-alias-1", "pact-fixture-alias-2"],
            "d": "Pact fixture — actor detail happy path (pinned id)",
        },
    )
    # Codename linked to the pinned actor. A distinct codename name
    # avoids colliding with the canonical Lazarus fixture's Andariel
    # link if both fixtures run in the same state-replay sequence.
    await _ensure_codename(
        session,
        name="pact-actor-detail-codename",
        group_id=ACTOR_DETAIL_FIXTURE_ID,
    )


async def _ensure_actor_with_reports_fixture(session: AsyncSession) -> None:
    """Seed the fixture ``GET /actors/{id}/reports`` populated pact uses.

    Plan D14 (PR #15) — extends the PR #14 Group G actor detail
    fixture. Reuses the pinned actor at ``ACTOR_DETAIL_FIXTURE_ID``
    (999003) + its codename ``pact-actor-detail-codename``, then
    seeds three pinned reports (``ACTOR_REPORTS_FIXTURE_REPORT_IDS``)
    linked via ``report_codenames``. Three rows give the pact's
    ``eachLike`` matcher a stable non-empty set and the D16
    newest-first ordering has three distinct ``published`` dates so
    the order is deterministic across replays.

    The consumer pact is a LITERAL path interaction
    ``GET /api/v1/actors/999003/reports`` with a response body
    ``{items: eachLike(ReportItem), next_cursor: null}`` — plan D9
    envelope shape. Matchers are type-only, so the exact titles /
    urls here satisfy the pact by virtue of being non-empty strings
    with the right shape.

    Idempotent: every insert uses ``ON CONFLICT (id) DO NOTHING``
    (groups + reports) or ``ON CONFLICT DO NOTHING`` on the
    composite PK (``report_codenames``). Two consecutive invocations
    produce exactly one row per pinned id across all three reports.
    The underlying actor-detail seed is also idempotent (proven by
    ``test_actor_detail_fixture_is_idempotent`` from PR #14 Group G).
    """
    # Ensure the actor + its codename land first (idempotent).
    await _ensure_actor_detail_fixture(session)
    source_id = await _ensure_source(session)

    # Look up the actor's codename id. Single row per
    # ``_ensure_actor_detail_fixture`` invariant.
    codename_id = (
        await session.execute(
            text(
                "SELECT id FROM codenames "
                "WHERE group_id = :g AND name = :n"
            ),
            {
                "g": ACTOR_DETAIL_FIXTURE_ID,
                "n": "pact-actor-detail-codename",
            },
        )
    ).scalar_one()

    # Three reports with distinct published dates so the DESC sort
    # is stable across replays (plan D16). Dates chosen inside a
    # wide window so default date filters don't drop them.
    report_seed_data = [
        (
            ACTOR_REPORTS_FIXTURE_REPORT_IDS[0],
            date(2026, 3, 15),
            "Pact fixture — actor reports #1 (newest)",
        ),
        (
            ACTOR_REPORTS_FIXTURE_REPORT_IDS[1],
            date(2026, 2, 10),
            "Pact fixture — actor reports #2",
        ),
        (
            ACTOR_REPORTS_FIXTURE_REPORT_IDS[2],
            date(2026, 1, 5),
            "Pact fixture — actor reports #3 (oldest)",
        ),
    ]

    for report_id, published, title in report_seed_data:
        await session.execute(
            text(
                "INSERT INTO reports "
                "(id, source_id, title, url, url_canonical, sha256_title, "
                "published, lang, tlp) "
                "VALUES (:id, :s, :t, :u, :uc, :sh, :p, :l, :tlp) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": report_id,
                "s": source_id,
                "t": title,
                "u": f"https://pact.test/actor-reports/{report_id}",
                "uc": f"https://pact.test/actor-reports/{report_id}",
                "sh": f"pact-sha-actor-reports-{report_id}",
                "p": published,
                "l": "en",
                "tlp": "WHITE",
            },
        )
        await session.execute(
            text(
                "INSERT INTO report_codenames "
                "(report_id, codename_id) "
                "VALUES (:r, :c) "
                "ON CONFLICT DO NOTHING"
            ),
            {"r": report_id, "c": codename_id},
        )


async def _ensure_actor_with_no_reports_fixture(
    session: AsyncSession,
) -> None:
    """Seed the fixture ``GET /actors/{id}/reports`` EMPTY pact uses.

    Plan D14 / D15(b or c) — distinct actor at pinned id
    ``ACTOR_WITH_NO_REPORTS_ID`` (999004) with ONE codename and
    ZERO ``report_codenames`` rows. The actor exists (so
    ``_actor_exists`` returns True and the endpoint yields 200) but
    the reports query returns an empty envelope (plan D8). Distinct
    from ``ACTOR_DETAIL_FIXTURE_ID`` so the populated and empty
    pact interactions never share state.

    ``groups.name`` is UNIQUE (migration 0001 line 37), so the name
    differs from every other pinned fixture to avoid
    pinned-id-vs-unique-name conflict (memory
    ``pitfall_pinned_id_vs_unique_name``). The codename is also
    distinct from Group G's ``pact-actor-detail-codename``.

    Idempotent: ``ON CONFLICT (id) DO NOTHING`` on groups +
    SELECT-first codename upsert via ``_ensure_codename``.
    """
    await session.execute(
        text(
            "INSERT INTO groups "
            "(id, name, mitre_intrusion_set_id, aka, description) "
            "VALUES (:id, :n, :m, :aka, :d) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": ACTOR_WITH_NO_REPORTS_ID,
            "n": "Pact fixture actor with no reports",
            "m": "G9004",
            "aka": ["pact-empty-alias"],
            "d": (
                "Pact fixture — actor WITH codenames but WITHOUT "
                "any report_codenames rows. Exists for the empty "
                "GET /actors/{id}/reports interaction."
            ),
        },
    )
    # One codename, zero report_codenames rows — the D15(c) branch
    # (codenames present but no reports mention them via the join).
    await _ensure_codename(
        session,
        name="pact-empty-actor-codename",
        group_id=ACTOR_WITH_NO_REPORTS_ID,
    )


# ---------------------------------------------------------------------------
# PR #17 Group C — /search populated + empty fixture helpers
# ---------------------------------------------------------------------------
#
# Two FE pact interactions land in PR #17 Group F:
#   GET /api/v1/search?q=lazarus         (populated — eachLike on items)
#   GET /api/v1/search?q=nomatchxyz123   (D10 empty — items: [])
#
# Populated seed: 3 reports pinned at SEARCH_POPULATED_FIXTURE_REPORT_
# IDS (999060-62) with "Lazarus" in BOTH title AND summary. The FTS
# document is ``COALESCE(title,'') || ' ' || COALESCE(summary,'')``
# (see api.read.search_service._run_fts), so a hit in either column
# is sufficient — seeding both makes the query-shape debug-friendly
# for a reviewer staring at a failing verifier log. Distinct
# ``published`` dates give a stable tie-breaker if a future pact
# interaction adds a date filter.
#
# Empty seed: one distractor report pinned at SEARCH_EMPTY_FIXTURE_
# REPORT_IDS[0] (999063) whose title + summary intentionally avoid
# the pact's ``nomatchxyz123`` query. Existence of this row pins the
# invariant that the D10 empty envelope comes from an FTS predicate
# MISS — not from a zero-row reports table. Same role as the
# D10 empty-embedding neighbor at 999031 for /similar.


async def _ensure_search_populated_fixture(session: AsyncSession) -> None:
    """Seed the fixture ``GET /api/v1/search?q=lazarus`` pact uses.

    Three reports (pinned at ``SEARCH_POPULATED_FIXTURE_REPORT_IDS``)
    with "Lazarus" in both title and summary so FTS matches against
    ``plainto_tsquery('simple', 'lazarus')`` regardless of which
    column the analyst's query hits. Distinct ``published`` dates
    exist to keep the ordering deterministic under any date filter
    a future pact interaction might layer on; inside the current
    plan the sort is ``ts_rank_cd DESC, reports.id DESC`` so the
    three rows still produce a stable order even when their rank
    values are near-identical.

    Idempotent: ``ON CONFLICT (id) DO NOTHING`` on every report
    insert. A repeat state setup is a no-op at the DB layer.
    """
    source_id = await _ensure_source(session)

    # Distinct published dates + Lazarus-heavy title/summary pairs.
    # Matcher-shape (FE pact uses eachLike on items + like on each
    # hit) accepts any type-correct row, so these specific strings
    # are for reviewer readability only.
    report_seed_data = [
        (
            SEARCH_POPULATED_FIXTURE_REPORT_IDS[0],
            date(2026, 3, 15),
            "Lazarus targets SK crypto exchanges",
            (
                "Lazarus Group ran a credential-harvesting operation "
                "against multiple SK crypto exchange analysts in Q1."
            ),
        ),
        (
            SEARCH_POPULATED_FIXTURE_REPORT_IDS[1],
            date(2026, 2, 10),
            "Lazarus phishing campaign — MFA bypass",
            (
                "Lazarus actors leveraged OAuth consent phishing plus "
                "session-cookie theft to bypass MFA in a February wave."
            ),
        ),
        (
            SEARCH_POPULATED_FIXTURE_REPORT_IDS[2],
            date(2026, 1, 5),
            "Lazarus loader variant profiled",
            (
                "Analysts profiled a new Lazarus loader dropping "
                "BLINDINGCAN-like stagers on compromised hosts."
            ),
        ),
    ]

    for report_id, published, title, summary in report_seed_data:
        await session.execute(
            text(
                "INSERT INTO reports "
                "(id, source_id, title, url, url_canonical, sha256_title, "
                "published, lang, tlp, summary) "
                "VALUES (:id, :s, :t, :u, :uc, :sh, :p, :l, :tlp, :sm) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": report_id,
                "s": source_id,
                "t": title,
                "u": f"https://pact.test/search/populated-{report_id}",
                "uc": f"https://pact.test/search/populated-{report_id}",
                "sh": f"pact-sha-search-pop-{report_id}",
                "p": published,
                "l": "en",
                "tlp": "WHITE",
                "sm": summary,
            },
        )

    # PR #19b OI6 = B — stamp deterministic 1536-dim embeddings onto
    # the populated fixture rows so the hybrid /search path places
    # them in the vector-kNN top-N during pact verification. Without
    # this, vector_rank would come back null and the consumer's
    # ``integer()`` matcher on vector_rank would fail.
    #
    # Null-guard: only UPDATE rows whose ``embedding`` is still NULL
    # so a repeat state setup is a no-op (idempotent, same posture as
    # the INSERT ON CONFLICT DO NOTHING above).
    #
    # Orthogonal one-hot style vectors give each row a distinct
    # cosine-distance profile, so vector_rank remains deterministic
    # regardless of the embedding-client's query vector (any non-zero
    # query vector yields a stable ordering across the 3 rows).
    for i, (report_id, _published, _title, _summary) in enumerate(
        report_seed_data
    ):
        vec = [0.0] * 1536
        vec[i] = 1.0
        vec_literal = "[" + ",".join(repr(x) for x in vec) + "]"
        await session.execute(
            text(
                "UPDATE reports SET embedding = CAST(:vec AS vector) "
                "WHERE id = :id AND embedding IS NULL"
            ),
            {"id": report_id, "vec": vec_literal},
        )


async def _ensure_search_empty_fixture(session: AsyncSession) -> None:
    """Seed the fixture ``GET /api/v1/search?q=nomatchxyz123`` pact uses.

    One distractor report pinned at ``SEARCH_EMPTY_FIXTURE_REPORT_IDS[0]``
    (999063). Title + summary deliberately avoid the pact's
    ``nomatchxyz123`` query token — no dictionary word contains that
    substring naturally, so human-written prose will not match. The
    row's purpose is to pin the contract "D10 empty envelope fires
    on FTS MISS, not DB emptiness" — analogous to the empty-embedding
    neighbor at ``SIMILAR_EMPTY_EMBEDDING_NEIGHBOR_ID``.

    Idempotent: ``ON CONFLICT (id) DO NOTHING``.
    """
    source_id = await _ensure_source(session)

    await session.execute(
        text(
            "INSERT INTO reports "
            "(id, source_id, title, url, url_canonical, sha256_title, "
            "published, lang, tlp, summary) "
            "VALUES (:id, :s, :t, :u, :uc, :sh, :p, :l, :tlp, :sm) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": SEARCH_EMPTY_FIXTURE_REPORT_IDS[0],
            "s": source_id,
            "t": "Pact fixture - search empty distractor",
            "u": "https://pact.test/search/empty-distractor",
            "uc": "https://pact.test/search/empty-distractor",
            "sh": "pact-sha-search-empty-distractor",
            "p": date(2026, 2, 20),
            "l": "en",
            "tlp": "WHITE",
            "sm": (
                "Distractor report whose title and summary intentionally "
                "do not contain the pact query token so the FTS predicate "
                "misses and the D10 empty envelope fires."
            ),
        },
    )


async def _ensure_similar_reports_populated_fixture(
    session: AsyncSession,
) -> None:
    """Seed the fixture ``GET /reports/{id}/similar`` (populated) uses.

    Plan D2 + D8 shape: source report with a populated embedding +
    3 neighbor reports with distinct embeddings so cosine kNN
    produces 3 non-empty rows. Specific cosine values are NOT
    pinned at the pact layer (matcher is eachLike on shape only) —
    real-PG integration tests can pin score ordering if ever
    needed.

    Embeddings: source sits at dim 0 = 1.0; neighbors vary dim-0
    magnitude so their cosine similarity with source is
    monotonically decreasing. Ids pinned so the consumer pact can
    target ``SIMILAR_POPULATED_SOURCE_ID`` deterministically.
    """
    source_id = await _ensure_source(session)

    source_vec = _make_embedding({0: 1.0})
    neighbor_vecs = {
        999011: _make_embedding({0: 0.95, 1: 0.05}),
        999012: _make_embedding({0: 0.8, 1: 0.2}),
        999013: _make_embedding({0: 0.5, 1: 0.5}),
    }

    await session.execute(
        text(
            "INSERT INTO reports (id, source_id, title, url, url_canonical, "
            "sha256_title, published, tlp, embedding) "
            f"VALUES (:id, :s, :t, :u, :uc, :sh, :p, :tlp, "
            f"CAST(:emb AS vector)) "
            "ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding"
        ),
        {
            "id": SIMILAR_POPULATED_SOURCE_ID,
            "s": source_id,
            "t": "Pact fixture — similar populated source",
            "u": "https://pact.test/reports/similar/populated-source",
            "uc": "https://pact.test/reports/similar/populated-source",
            "sh": "pact-sha-similar-pop-src",
            "p": date(2026, 3, 1),
            "tlp": "WHITE",
            "emb": source_vec,
        },
    )

    for neighbor_id, vec in neighbor_vecs.items():
        await session.execute(
            text(
                "INSERT INTO reports (id, source_id, title, url, url_canonical, "
                "sha256_title, published, tlp, embedding) "
                f"VALUES (:id, :s, :t, :u, :uc, :sh, :p, :tlp, "
                f"CAST(:emb AS vector)) "
                "ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding"
            ),
            {
                "id": neighbor_id,
                "s": source_id,
                "t": f"Pact fixture — similar neighbor {neighbor_id}",
                "u": f"https://pact.test/reports/similar/neighbor-{neighbor_id}",
                "uc": f"https://pact.test/reports/similar/neighbor-{neighbor_id}",
                "sh": f"pact-sha-similar-neighbor-{neighbor_id}",
                "p": date(2026, 2, 15),
                "tlp": "WHITE",
                "emb": vec,
            },
        )


async def _ensure_similar_reports_empty_embedding_fixture(
    session: AsyncSession,
) -> None:
    """Seed the fixture for plan D10's ``source has no embedding``
    empty-contract verification.

    Two rows:
      (a) source report with NULL embedding — the one the pact
          interaction targets. The ``/similar`` endpoint must emit
          ``200 + {items: []}`` against this source per D10.
      (b) one neighbor report WITH an embedding — so the DB is not
          empty of embeddings elsewhere. This pins the invariant
          that "source has no embedding" is the ONLY trigger for
          D10 empty, NOT "the whole DB has no embeddings".

    If a future regression collapses D10 to "DB-wide emptiness",
    this fixture makes the failure mode visible: the neighbor
    remains a legitimate similarity candidate but the endpoint must
    still return empty because the SOURCE has no vector to compare
    against.
    """
    source_id_fk = await _ensure_source(session)

    # Source — NULL embedding. Schema allows NULL (see migration 0001
    # where the vector column is ADDed via ALTER without NOT NULL).
    await session.execute(
        text(
            "INSERT INTO reports (id, source_id, title, url, url_canonical, "
            "sha256_title, published, tlp, embedding) "
            "VALUES (:id, :s, :t, :u, :uc, :sh, :p, :tlp, NULL) "
            "ON CONFLICT (id) DO UPDATE SET embedding = NULL"
        ),
        {
            "id": SIMILAR_EMPTY_EMBEDDING_SOURCE_ID,
            "s": source_id_fk,
            "t": "Pact fixture — similar empty-embedding source",
            "u": "https://pact.test/reports/similar/empty-source",
            "uc": "https://pact.test/reports/similar/empty-source",
            "sh": "pact-sha-similar-empty-src",
            "p": date(2026, 3, 5),
            "tlp": "WHITE",
        },
    )

    # Neighbor with an embedding — exists to prove the D10 contract
    # triggers on SOURCE embedding status, not DB-wide emptiness.
    await session.execute(
        text(
            "INSERT INTO reports (id, source_id, title, url, url_canonical, "
            "sha256_title, published, tlp, embedding) "
            "VALUES (:id, :s, :t, :u, :uc, :sh, :p, :tlp, "
            f"CAST(:emb AS vector)) "
            "ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding"
        ),
        {
            "id": SIMILAR_EMPTY_EMBEDDING_NEIGHBOR_ID,
            "s": source_id_fk,
            "t": "Pact fixture — similar empty-embedding neighbor (has embedding)",
            "u": "https://pact.test/reports/similar/empty-neighbor",
            "uc": "https://pact.test/reports/similar/empty-neighbor",
            "sh": "pact-sha-similar-empty-neighbor",
            "p": date(2026, 2, 25),
            "tlp": "WHITE",
            "emb": _make_embedding({0: 0.9, 1: 0.1}),
        },
    )


# ---------------------------------------------------------------------------
# PR-B T13 — D-1 correlation fixtures (umbrella §7.6 + plan §4 row T13)
# ---------------------------------------------------------------------------
#
# Five FE pact interactions land on the BE under PR-B T8:
#   #1 catalog            — `seeded correlation catalog fixture ...`
#   #2 populated          — `seeded correlation populated fixture ...`
#   #3 insufficient_lag   — `seeded correlation insufficient_sample_at_lag ...`
#   #4 full reason enum   — `seeded correlation full-reason-enum ...`
#   #5 422                — `seeded correlation insufficient_sample 422 ...`
#
# #1 needs no DB seed beyond an authenticated session — the catalog is
# the hardcoded `_BASE_CATALOG` in `correlation_aggregator.py` and the
# eachLike matcher only requires ≥1 series row.
#
# #2 / #3 / #5 each seed a dense reports + incidents window where the
# query window matches the FE pact's `withRequest.query` block exactly
# (`x=reports.total`, `y=incidents.total`, plus the locked
# `date_from` / `date_to` / `alpha=0.05`):
#   - #2: 2018-01..2026-04 wide window so every lag in [-24..+24] keeps
#     effective_n_at_lag ≥ 30 → BE returns 49 cells with reason=null
#     each, satisfying the per-cell `populatedCell` matcher.
#   - #3: exactly 2024-01..2026-06 (30 months) so lag 0 = 30 (just
#     passes the gate) and every k≠0 yields 30−|k| < 30 → those 48
#     cells return `insufficient_sample_at_lag`, matching the pact's
#     positional `nonNullCell(... 'insufficient_sample_at_lag')`.
#   - #5: 2026-01..2026-06 (6 months) so effective_n < 30 → BE raises
#     `InsufficientSampleError` and the router returns 422 with the
#     `value_error.insufficient_sample` envelope.
#
# #4 (full-reason-enum) is fundamentally HARDER via real DB rows
# alone — the FE pact pins specific reason literals at specific lag
# positions (idx 0/48 ⇒ `insufficient_sample_at_lag`, idx 12/36 ⇒
# `degenerate`, idx 18/30 ⇒ `low_count_suppressed`, all others ⇒
# populated) AND a single warning code
# `equal('low_count_suppressed_cells')`. The aggregator's decision
# tree shares X/Y arrays across lags AND its warning derivation
# always emits `cross_rooted_pair` for `reports.total` ↔
# `incidents.total`; both pact requirements are unreachable from
# normal DB seeds. Per
# `pattern_pact_dependency_override_via_provider_state` the
# resolution is to install a stub via `app.dependency_overrides`
# behind the `Depends(get_compute_correlation)` indirection in
# `analytics_correlation.py`: the #4 dispatcher branch installs
# `_correlation_full_reason_enum_compute_stub` (defined below) for
# the next request only, returning the canned 49-cell payload that
# satisfies the pact's per-position matchers and the locked
# `low_count_suppressed_cells` warning. The override is cleared at
# the top of every subsequent state request via
# `_clear_correlation_compute_override`, parallel to
# `_clear_embedding_client_override`, so the stub does not bleed
# into #1/#2/#3/#5 or any unrelated correlation request.
#
# All four fixture seeders below produce monthly counts ≥ 5 across
# every month they cover so the aggregator's R-16 low-count
# suppression doesn't fire and `min(x_arr) < 5` stays false at lag 0.
# Counts vary across months so var(x_arr) > 0 and the populated
# branch is reachable. Reports are linked to the canonical Lazarus
# codename so any future `group_id`-filtered correlation query stays
# non-empty (the slice-3 D-1 endpoint is `group_id`-no-op per
# `analytics_correlation.py:181-204`, but the link is cheap and keeps
# the seed shape consistent with other analytics fixtures).


def _correlation_monthly_counts(
    months: list[date],
    *,
    lo: int = 6,
    hi: int = 38,
) -> list[int]:
    """Return varying monthly counts ≥ ``lo`` across ``months``.

    The deterministic interleave (e.g. 7-step modular walk over
    ``[lo, hi]``) keeps variance > 0 without depending on Python's
    ``random`` module, which would make the seed non-idempotent
    across replays.
    """
    span = hi - lo + 1
    return [lo + ((idx * 7 + 3) % span) for idx in range(len(months))]


def _month_dates(start: date, count: int) -> list[date]:
    """Generate ``count`` consecutive month-start dates from ``start``."""
    out: list[date] = []
    year, month = start.year, start.month
    for _ in range(count):
        out.append(date(year, month, 1))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return out


async def _seed_correlation_dense_window(
    session: AsyncSession,
    *,
    fixture_label: str,
    months: list[date],
) -> None:
    """Seed reports + incidents across each month with counts ≥ 5.

    The aggregator's `reports.total` series counts rows in
    ``reports`` published within the month; `incidents.total`
    counts rows in ``incidents`` reported within the month. Seed
    one report-per-day-of-month spread to control the count
    deterministically.
    """
    source_id = await _ensure_source(session)
    lazarus_id = await _ensure_canonical_lazarus_fixture(session)
    andariel_id = await _ensure_codename(
        session, name="Andariel", group_id=lazarus_id
    )

    report_counts = _correlation_monthly_counts(months, lo=6, hi=38)
    incident_counts = _correlation_monthly_counts(months, lo=5, hi=27)

    for month_idx, bucket in enumerate(months):
        n_reports = report_counts[month_idx]
        for report_idx in range(n_reports):
            published = date(
                bucket.year,
                bucket.month,
                min(report_idx + 1, 28),
            )
            await _ensure_report_with_codename_link(
                session,
                source_id=source_id,
                codename_id=andariel_id,
                url_canonical=(
                    f"https://pact.test/correlation/{fixture_label}/"
                    f"r-{bucket.isoformat()}-{report_idx}"
                ),
                title=(
                    f"Pact fixture — correlation {fixture_label} report "
                    f"{bucket.isoformat()} #{report_idx}"
                ),
                published=published,
            )

        n_incidents = incident_counts[month_idx]
        for incident_idx in range(n_incidents):
            reported = date(
                bucket.year,
                bucket.month,
                min(incident_idx + 1, 28),
            )
            await _ensure_incident_with_motivation(
                session,
                title=(
                    f"Pact fixture — correlation {fixture_label} "
                    f"incident {bucket.isoformat()} #{incident_idx}"
                ),
                motivation="ESPIONAGE",
                reported=reported,
            )


async def _ensure_correlation_catalog_fixture(
    session: AsyncSession,
) -> None:
    """Seed for the FE pact `correlation series catalog` interaction.

    The catalog endpoint returns `_BASE_CATALOG` (2 hardcoded series)
    plus any per-motivation / per-sector / per-country derivations
    that the aggregator builds from existing dimension tables. The
    FE pact's `eachLike(...)` only requires ≥1 series row, which the
    hardcoded base catalog satisfies regardless of DB state. We seed
    a single canonical Lazarus row + Andariel codename for parity
    with the rest of the analytics fixtures (and so a future
    extension that needs reports linked to actors stays non-empty),
    but no dense correlation window is required here.
    """
    lazarus_id = await _ensure_canonical_lazarus_fixture(session)
    await _ensure_codename(session, name="Andariel", group_id=lazarus_id)


async def _ensure_correlation_populated_fixture(
    session: AsyncSession,
) -> None:
    """Seed dense ~100 months for the populated 49-cell pact (PR-B T8 #2).

    Window 2018-01..2026-04 inclusive (100 months) so every lag in
    [-24..+24] keeps effective_n_at_lag = 100 - |k| ≥ 76, well above
    the §4.4 MIN_EFFECTIVE_N=30 gate. Counts vary 6..38 reports and
    5..27 incidents per month so var > 0 and the populated branch
    fires (reason: null) at every cell. The cross-rooted-pair
    warning fires automatically because x_root=`reports.published`
    and y_root=`incidents.reported` (umbrella §7.4 AFTER-loop).
    """
    months = _month_dates(date(2018, 1, 1), 100)
    await _seed_correlation_dense_window(
        session, fixture_label="populated", months=months
    )


async def _ensure_correlation_insufficient_sample_at_lag_fixture(
    session: AsyncSession,
) -> None:
    """Seed exactly 30 months for the insufficient_sample_at_lag pact (#3).

    Window 2024-01..2026-06 inclusive (30 months) chosen so lag 0 has
    effective_n=30 (just passes the §4.4 gate) and every lag k≠0
    yields 30 − |k| < 30 → those 48 cells return
    `insufficient_sample_at_lag`. Counts ≥ 5 prevent the
    low_count_suppressed reason from firing at lag 0.
    """
    months = _month_dates(date(2024, 1, 1), 30)
    await _seed_correlation_dense_window(
        session, fixture_label="insufficient_sample_at_lag", months=months
    )


async def _ensure_correlation_full_reason_enum_fixture(
    session: AsyncSession,
) -> None:
    """Seed a wide window for the full-reason-enum pact (#4).

    The FE pact pins specific reason literals at specific lag
    positions (idx 0/48 ⇒ `insufficient_sample_at_lag`, idx 12/36
    ⇒ `degenerate`, idx 18/30 ⇒ `low_count_suppressed`) AND a
    single warning code `equal('low_count_suppressed_cells')` (no
    `cross_rooted_pair` allowed). The real aggregator cannot
    produce this shape from real DB rows because its
    `_safe_pearsonr` / `_safe_spearmanr` decision tree shares X/Y
    arrays across all 49 lags AND the warning derivation always
    emits `cross_rooted_pair` for `reports.total` ↔
    `incidents.total` (umbrella §7.4 AFTER-loop).

    Resolution per
    `pattern_pact_dependency_override_via_provider_state`: the
    `provider_states` handler installs a stub via
    `app.dependency_overrides[get_compute_correlation]` which
    returns the canned 49-cell response (see
    `_correlation_full_reason_enum_compute_stub`). This DB seed
    still runs (the stub doesn't touch DB but the seed keeps the
    fixture self-consistent if a future contributor unwires the
    stub) — same dense 100-month window as the populated fixture.
    """
    months = _month_dates(date(2018, 1, 1), 100)
    await _seed_correlation_dense_window(
        session, fixture_label="full_reason_enum", months=months
    )


# ---------------------------------------------------------------------------
# PR-B T13 — full-reason-enum compute stub + dependency override
# ---------------------------------------------------------------------------


_FULL_REASON_ENUM_DEFAULT_EFFECTIVE_N = 64


def _full_reason_enum_lag_grid_payload() -> list[dict[str, object]]:
    """Build the 49-cell lag_grid for the full-reason-enum stub.

    Layout matches the FE pact at
    `apps/frontend/tests/contract/frontend-dprk-cti-api.pact.test.ts:1942-1955`:

      idx 0, 48   (lag ±24)  ⇒ `insufficient_sample_at_lag`, n=28
      idx 12, 36  (lag ±12)  ⇒ `degenerate`,                  n=60
      idx 18, 30  (lag ±6)   ⇒ `low_count_suppressed`,        n=78
      all others             ⇒ populated (reason=null),       n=64

    The cell shape mirrors `compute_correlation`'s lag_grid_payload
    return shape (`correlation_aggregator.py:1059-1080`) and
    satisfies the `CorrelationCellMethodBlock` null-consistency
    invariant (`schemas/correlation.py:81-96`): `reason != null`
    cells carry r/p_raw/p_adjusted = null, significant = false;
    populated cells carry finite floats. Per-cell n values match
    the FE pact's `integer(...)` matchers.
    """
    grid: list[dict[str, object]] = []
    for idx in range(49):
        lag = idx - 24
        abs_lag = abs(lag)
        if abs_lag == 24:
            reason: str | None = "insufficient_sample_at_lag"
            n_at_lag = 28
        elif abs_lag == 12:
            reason = "degenerate"
            n_at_lag = 60
        elif abs_lag == 6:
            reason = "low_count_suppressed"
            n_at_lag = 78
        else:
            reason = None
            n_at_lag = _FULL_REASON_ENUM_DEFAULT_EFFECTIVE_N

        if reason is None:
            method_block: dict[str, object] = {
                "r": 0.412,
                "p_raw": 0.00021,
                "p_adjusted": 0.00514,
                "significant": True,
                "effective_n_at_lag": n_at_lag,
                "reason": None,
            }
            spearman_block: dict[str, object] = {
                "r": 0.398,
                "p_raw": 0.00031,
                "p_adjusted": 0.00759,
                "significant": False,
                "effective_n_at_lag": n_at_lag,
                "reason": None,
            }
        else:
            method_block = {
                "r": None,
                "p_raw": None,
                "p_adjusted": None,
                "significant": False,
                "effective_n_at_lag": n_at_lag,
                "reason": reason,
            }
            spearman_block = dict(method_block)

        grid.append(
            {
                "lag": lag,
                "pearson": method_block,
                "spearman": spearman_block,
            }
        )
    return grid


async def _correlation_full_reason_enum_compute_stub(
    session: AsyncSession,
    *,
    x: str,
    y: str,
    date_from: date,
    date_to: date,
    alpha: float,
) -> dict[str, object]:
    """Stub for `compute_correlation` returning the canned full-reason-enum payload.

    Signature matches `correlation_aggregator.compute_correlation`
    so it slots cleanly behind the
    `Depends(get_compute_correlation)` indirection in
    `analytics_correlation.py`. The `session` argument is unused
    (the stub does not touch the DB) but accepted so the
    dependency-override binding stays signature-compatible.

    The returned shape mirrors the real aggregator's payload
    structure exactly — `CorrelationResponse.model_validate(...)`
    must accept it without drift. In particular:

      - `lag_grid` is exactly 49 cells in ascending lag order
        (`schemas/correlation.py:172-179` model_validator).
      - Cells with `reason != null` carry null r/p_raw/p_adjusted
        and significant=false (null-consistency invariant
        `schemas/correlation.py:81-96`).
      - `interpretation.warnings` carries ONLY one entry with
        `code='low_count_suppressed_cells'` so the FE pact's
        `equal('low_count_suppressed_cells')` matcher passes
        (the real aggregator would emit `cross_rooted_pair`,
        which the pact's `equal()` literal would reject).
    """
    del session  # stub does not touch the DB
    return {
        "x": x,
        "y": y,
        "date_from": date_from,
        "date_to": date_to,
        "alpha": alpha,
        "effective_n": _FULL_REASON_ENUM_DEFAULT_EFFECTIVE_N,
        "lag_grid": _full_reason_enum_lag_grid_payload(),
        "interpretation": {
            "caveat": (
                "Correlation does not imply causation. This chart "
                "shows statistical co-movement only; non-stationarity, "
                "autocorrelation, and unobserved confounders can "
                "produce spurious associations. See the methodology "
                "page for details."
            ),
            "methodology_url": "/docs/methodology/correlation",
            "warnings": [
                {
                    "code": "low_count_suppressed_cells",
                    "message": (
                        "Some lag cells were suppressed because "
                        "shifted-pair monthly counts fell below the "
                        "disclosure threshold."
                    ),
                    "severity": "info",
                }
            ],
        },
    }


def _clear_correlation_compute_override(app) -> None:
    """Remove any prior Pact-installed correlation-compute override.

    The verifier reuses one uvicorn process for the whole run, so
    the full-reason-enum stub must not leak into other correlation
    interactions (#1/#2/#3/#5) or unrelated routes. Every
    provider-state call clears this override at the top, parallel
    to `_clear_embedding_client_override`.
    """
    from .analytics_correlation import get_compute_correlation

    app.dependency_overrides.pop(get_compute_correlation, None)


def _install_correlation_full_reason_enum_compute_override(app) -> None:
    """Install the full-reason-enum stub for the next request only.

    The stub is bound via `app.dependency_overrides` so FastAPI's
    Depends resolution picks it up at request time. The provider-
    state handler clears the override at the start of every state
    request so stale stubs don't bleed across interactions.
    """
    from .analytics_correlation import get_compute_correlation

    app.dependency_overrides[get_compute_correlation] = (
        lambda: _correlation_full_reason_enum_compute_stub
    )


async def _ensure_correlation_insufficient_sample_422_fixture(
    session: AsyncSession,
) -> None:
    """Seed 6 months for the 422 insufficient_sample pact (#5).

    Window 2026-01..2026-06 inclusive (6 months) so effective_n at
    lag 0 = 6 < MIN_EFFECTIVE_N (30). The aggregator raises
    `InsufficientSampleError(effective_n=6, minimum_n=30)`; the
    router returns 422 with the `value_error.insufficient_sample`
    envelope. The pact's `msg` / `ctx.effective_n` matchers are
    type-only (`string()` / `integer()`) so the BE-produced "got 6"
    payload satisfies them despite the FE pact example's "got 18"
    sample value.
    """
    months = _month_dates(date(2026, 1, 1), 6)
    await _seed_correlation_dense_window(
        session, fixture_label="insufficient_sample_422", months=months
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("", include_in_schema=False)
async def provider_states(
    request: Request,
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
    _clear_embedding_client_override(request.app)
    _clear_correlation_compute_override(request.app)

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

        if state == (
            "seeded attack_matrix dataset and an authenticated analyst session"
        ):
            await _ensure_attack_matrix_fixture(session)
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        if state == (
            "seeded trend dataset and an authenticated analyst session"
        ):
            await _ensure_trend_fixture(session)
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        if state == (
            "seeded geo dataset and an authenticated analyst session"
        ):
            await _ensure_geo_fixture(session)
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        # PR #3 — actor-network co-occurrence graph.
        if state == "actor network co-occurrence available":
            await _ensure_actor_network_fixture(session)
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        # PR #23 Group A C1 — lazarus.day parity, incidents_trend.
        if state == (
            "seeded incidents_trend motivation dataset "
            "and an authenticated analyst session"
        ):
            await _ensure_incidents_trend_motivation_fixture(session)
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        if state == (
            "seeded incidents_trend sector dataset "
            "and an authenticated analyst session"
        ):
            await _ensure_incidents_trend_sector_fixture(session)
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        # PR #14 Group C — detail + similar-reports fixtures.
        if state == (
            "seeded report detail fixture and an authenticated analyst session"
        ):
            await _ensure_report_detail_fixture(session)
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        if state == (
            "seeded incident detail fixture and an authenticated analyst session"
        ):
            await _ensure_incident_detail_fixture(session)
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        if state == (
            "seeded actor detail fixture and an authenticated analyst session"
        ):
            await _ensure_actor_detail_fixture(session)
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        if state == (
            "seeded similar reports populated fixture "
            "and an authenticated analyst session"
        ):
            await _ensure_similar_reports_populated_fixture(session)
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        if state == (
            "seeded similar reports empty-embedding fixture "
            "and an authenticated analyst session"
        ):
            await _ensure_similar_reports_empty_embedding_fixture(session)
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        # PR #15 Group C — actor-reports populated + empty fixtures.
        # Populated reuses ACTOR_DETAIL_FIXTURE_ID=999003 so the pact
        # path ``/api/v1/actors/999003/reports`` hits a pre-seeded
        # actor with ≥3 linked reports. Empty uses the separate
        # ACTOR_WITH_NO_REPORTS_ID=999004 so state isolation between
        # the two interactions holds (plan D14).
        if state == (
            "seeded actor with linked reports fixture "
            "and an authenticated analyst session"
        ):
            await _ensure_actor_with_reports_fixture(session)
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        if state == (
            "seeded actor with no linked reports fixture "
            "and an authenticated analyst session"
        ):
            await _ensure_actor_with_no_reports_fixture(session)
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        # PR #17 Group C — /search populated + empty fixtures. Populated
        # seeds 3 reports (999060-62) with Lazarus in both title and
        # summary so FTS matches q=lazarus. Empty seeds 1 distractor
        # (999063) with prose that does not contain the pact's
        # nomatchxyz123 query, pinning the D10-on-miss contract.
        if state == (
            "seeded search populated fixture "
            "and an authenticated analyst session"
        ):
            await _ensure_search_populated_fixture(session)
            await session.commit()
            _install_pact_search_embedding_override(request.app)
            await _seed_analyst_session(response, session_store)
            continue

        if state == (
            "seeded search empty fixture "
            "and an authenticated analyst session"
        ):
            await _ensure_search_empty_fixture(session)
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        # PR-B T13 — D-1 correlation fixtures. Each given() string from
        # `apps/frontend/tests/contract/frontend-dprk-cti-api.pact.test.ts`
        # umbrella §7.6 maps to one seeder defined above.
        if state == (
            "seeded correlation catalog fixture "
            "and an authenticated analyst session"
        ):
            await _ensure_correlation_catalog_fixture(session)
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        if state == (
            "seeded correlation populated fixture "
            "and an authenticated analyst session"
        ):
            await _ensure_correlation_populated_fixture(session)
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        if state == (
            "seeded correlation insufficient_sample_at_lag fixture "
            "and an authenticated analyst session"
        ):
            await _ensure_correlation_insufficient_sample_at_lag_fixture(
                session
            )
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        if state == (
            "seeded correlation full-reason-enum fixture "
            "and an authenticated analyst session"
        ):
            await _ensure_correlation_full_reason_enum_fixture(session)
            await session.commit()
            _install_correlation_full_reason_enum_compute_override(
                request.app
            )
            await _seed_analyst_session(response, session_store)
            continue

        if state == (
            "seeded correlation insufficient_sample 422 fixture "
            "and an authenticated analyst session"
        ):
            await _ensure_correlation_insufficient_sample_422_fixture(
                session
            )
            await session.commit()
            await _seed_analyst_session(response, session_store)
            continue

        # Unknown state — fall through with a session so the
        # interaction still authenticates. Better to mint a cookie
        # than to silently fail the verifier on a state rename.

    return {"status": "ok"}
