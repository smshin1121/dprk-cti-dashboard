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

        # Unknown state — fall through with a session so the
        # interaction still authenticates. Better to mint a cookie
        # than to silently fail the verifier on a state rename.

    return {"status": "ok"}
