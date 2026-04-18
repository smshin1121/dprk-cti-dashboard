"""Real-PG test: provider-state fixtures satisfy the FE pact matchers.

PR #12 Group I P1 regression guard. The FE pact in
``apps/frontend/tests/contract/frontend-dprk-cti-api.pact.test.ts``
uses strict matchers on the ``/actors`` and ``/dashboard/summary``
responses (``eachLike(...)`` rejects empty arrays;
``MatchersV3.string(...)`` rejects ``null``). A state-setup handler
that mints only skeleton rows would pass the HTTP contract but
immediately fail live verification.

These tests:
  1. Run the state helpers (same code-path the ``contract-verify``
     CI job invokes via POST ``/_pact/provider_states``).
  2. Hit the SAME read APIs the pact interactions target.
  3. Assert the response satisfies the strictest matcher each pact
     declares.

If a future edit loosens a fixture (e.g., stops seeding a codename
or a report-codename link), these tests flip red BEFORE the pact
verifier does — cheaper signal, clearer stack trace, no network.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import AsyncIterator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


pytestmark = pytest.mark.integration


_PG_URL = os.environ.get("POSTGRES_TEST_URL")

if not _PG_URL:
    pytest.skip(
        "POSTGRES_TEST_URL not set — pact-state integration tests skipped.",
        allow_module_level=True,
    )


from api.routers.pact_states import (  # noqa: E402
    _ensure_attack_matrix_fixture,
    _ensure_canonical_lazarus_fixture,
    _ensure_dashboard_fixture,
    _ensure_geo_fixture,
    _ensure_min_actors,
    _ensure_trend_fixture,
)
from api.read.analytics_aggregator import (  # noqa: E402
    compute_attack_matrix,
    compute_geo,
    compute_trend,
)
from api.read.dashboard_aggregator import compute_dashboard_summary  # noqa: E402
from api.read.repositories import list_actors  # noqa: E402


@pytest_asyncio.fixture(scope="module")
async def pg_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(_PG_URL, future=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_session(
    pg_engine: AsyncEngine,
) -> AsyncIterator[AsyncSession]:
    sm = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with sm() as session:
        yield session


@pytest_asyncio.fixture
async def clean_pg(pg_engine: AsyncEngine) -> None:
    async with pg_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "TRUNCATE report_tags, report_codenames, report_techniques, "
                "reports, tags, techniques, "
                "sources, codenames, groups, "
                "incident_motivations, incident_sectors, "
                "incident_countries, incidents "
                "RESTART IDENTITY CASCADE"
            )
        )


async def test_dashboard_fixture_satisfies_each_pact_matcher(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """``seeded reports/incidents/actors and an authenticated analyst
    session`` must produce non-empty arrays for every
    ``eachLike(...)`` field on /dashboard/summary UNDER THE EXACT
    FILTER the pact request sends.

    The pact interaction is
    ``GET /api/v1/dashboard/summary?date_from=2026-01-01&date_to=2026-04-18&group_id=1&group_id=3``.
    A fixture that seeds dates outside that window passes a
    no-filter aggregator call but empties the arrays at verify time
    (caught as the Group I CI red). This test invokes the aggregator
    with the same filter so the fixture stays in lockstep with the
    pact's request shape.
    """
    from datetime import date

    await _ensure_dashboard_fixture(pg_session)
    await pg_session.commit()

    summary = await compute_dashboard_summary(
        pg_session,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 4, 18),
        group_ids=[1, 3],
    )

    # Pact: reports_by_year = eachLike({year, count}) — ≥1 entry.
    assert summary["reports_by_year"], (
        "reports_by_year is empty — /dashboard/summary pact's "
        "eachLike matcher will fail. _ensure_dashboard_fixture must "
        "seed at least one report."
    )
    first_year = summary["reports_by_year"][0]
    assert isinstance(first_year["year"], int)
    assert isinstance(first_year["count"], int) and first_year["count"] >= 1

    # Pact: incidents_by_motivation = eachLike({motivation, count}).
    assert summary["incidents_by_motivation"], (
        "incidents_by_motivation is empty — pact eachLike will fail. "
        "Seed at least one incident_motivations row."
    )
    first_mot = summary["incidents_by_motivation"][0]
    assert isinstance(first_mot["motivation"], str)
    assert first_mot["motivation"]

    # Pact: top_groups = eachLike({group_id, name, report_count}).
    # This is the most brittle chain (reports → report_codenames →
    # codenames → groups) so a broken fixture most often surfaces here.
    assert summary["top_groups"], (
        "top_groups is empty — the reports→codenames→groups chain "
        "is broken. Check _ensure_report_with_codename_link wires "
        "both the report row AND the report_codenames FK row."
    )
    first_tg = summary["top_groups"][0]
    assert isinstance(first_tg["group_id"], int)
    assert isinstance(first_tg["name"], str) and first_tg["name"]
    assert isinstance(first_tg["report_count"], int)
    assert first_tg["report_count"] >= 1


async def test_actor_canonical_fixture_satisfies_each_pact_matcher(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """``seeded actors and an authenticated session`` must produce
    actor rows where EVERY field the /actors pact names is non-empty/
    non-null (aka, description, mitre_intrusion_set_id, codenames)."""
    await _ensure_canonical_lazarus_fixture(pg_session)
    await pg_session.commit()

    rows, total = await list_actors(pg_session, limit=50, offset=0)

    assert total >= 1, "canonical fixture must create at least one actor"
    for row in rows:
        assert row["mitre_intrusion_set_id"] is not None, (
            "pact: MatchersV3.string('G0032') rejects null"
        )
        assert (
            isinstance(row["aka"], list) and len(row["aka"]) >= 1
        ), "pact: aka = eachLike('APT38') rejects empty array"
        assert row["description"] is not None, (
            "pact: description = string('DPRK-attributed group') "
            "rejects null"
        )
        assert (
            isinstance(row["codenames"], list)
            and len(row["codenames"]) >= 1
        ), "pact: codenames = eachLike('Andariel') rejects empty array"


async def test_actor_min_100_fixture_keeps_shape_on_page_two(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """The actors page-2 pact interaction (offset=50) replays the
    same ``eachLike`` matcher over page-2 rows. Filler actors MUST
    therefore carry the same field shape as the canonical row —
    otherwise live verify fails on row #51 even though row #1 was
    fine."""
    await _ensure_canonical_lazarus_fixture(pg_session)
    await _ensure_min_actors(pg_session, 100)
    await pg_session.commit()

    rows, total = await list_actors(pg_session, limit=50, offset=50)

    assert total >= 100, "seed should create at least 100 total actors"
    assert len(rows) >= 1, "page 2 (offset=50) should have rows"
    for row in rows:
        assert row["mitre_intrusion_set_id"] is not None, (
            f"page-2 row {row['name']!r} missing mitre_intrusion_set_id"
        )
        assert len(row["aka"]) >= 1, (
            f"page-2 row {row['name']!r} has empty aka"
        )
        assert row["description"] is not None, (
            f"page-2 row {row['name']!r} has null description"
        )
        assert len(row["codenames"]) >= 1, (
            f"page-2 row {row['name']!r} has no linked codename"
        )


async def test_pact_state_helpers_are_idempotent(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """pact-ruby calls the state endpoint before every interaction,
    so the same state name fires multiple times in one verify run.
    The helpers must tolerate repeat calls without UNIQUE violations
    or duplicate inserts."""
    await _ensure_dashboard_fixture(pg_session)
    await _ensure_dashboard_fixture(pg_session)  # second call
    await _ensure_canonical_lazarus_fixture(pg_session)  # overlap
    await pg_session.commit()

    # Exactly one Lazarus group — not two.
    count = (
        await pg_session.execute(
            sa.text("SELECT COUNT(*) FROM groups WHERE name = 'Lazarus Group'")
        )
    ).scalar_one()
    assert count == 1

    # Exactly one Andariel codename.
    count = (
        await pg_session.execute(
            sa.text("SELECT COUNT(*) FROM codenames WHERE name = 'Andariel'")
        )
    ).scalar_one()
    assert count == 1

    # Dashboard still coherent after repeat seeding.
    summary = await compute_dashboard_summary(pg_session)
    assert summary["top_groups"]
    assert summary["reports_by_year"]
    assert summary["incidents_by_motivation"]


# ---------------------------------------------------------------------------
# PR #13 Group B — analytics fixtures matcher-shape + idempotency guards
# ---------------------------------------------------------------------------
#
# Same pattern as the dashboard fixture test above: run the helper,
# invoke the aggregator UNDER THE EXPECTED PACT FILTER, assert each
# ``eachLike(...)`` array is non-empty and each sub-field is typed
# correctly. The filter window mirrors the committed dashboard pact
# interaction (date_from=2026-01-01, date_to=2026-04-18); the Group J
# analytics pact interactions are expected to use the same window.


async def test_attack_matrix_fixture_satisfies_pact_matchers(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """``/analytics/attack_matrix`` pact will use
    ``{tactics: eachLike({id, name}), rows: eachLike({tactic_id,
    techniques: eachLike({technique_id, count})})}``. Each eachLike
    requires at least one row; string fields reject null.
    """
    from datetime import date

    await _ensure_attack_matrix_fixture(pg_session)
    await pg_session.commit()

    matrix = await compute_attack_matrix(
        pg_session,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 4, 18),
    )

    assert matrix["tactics"], (
        "tactics is empty — /analytics/attack_matrix pact's eachLike "
        "will fail. Fixture must produce at least one tactic row under "
        "the filter window."
    )
    assert matrix["rows"], (
        "rows is empty — check the report → report_techniques → "
        "techniques chain and confirm the reports' published dates "
        "are inside 2026-01-01..2026-04-18."
    )

    for tactic in matrix["tactics"]:
        assert isinstance(tactic["id"], str) and tactic["id"], (
            "pact: TacticRef.id = string(...) rejects null/empty"
        )
        assert isinstance(tactic["name"], str) and tactic["name"], (
            "pact: TacticRef.name = string(...) rejects null/empty"
        )

    for row in matrix["rows"]:
        assert isinstance(row["tactic_id"], str) and row["tactic_id"]
        assert row["techniques"], (
            f"tactic {row['tactic_id']!r} has empty techniques array "
            "— eachLike inside rows will fail"
        )
        for technique in row["techniques"]:
            assert (
                isinstance(technique["technique_id"], str)
                and technique["technique_id"]
            ), "pact: AttackTechniqueCount.technique_id rejects null"
            assert (
                isinstance(technique["count"], int)
                and technique["count"] >= 1
            ), "pact: AttackTechniqueCount.count integer(≥1) under eachLike"


async def test_attack_matrix_fixture_survives_group_filter(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """The attack_matrix fixture links its reports to the Lazarus
    codename, so a Group J pact that includes a ``group_id=1`` filter
    (matching the dashboard pact's convention) still produces a
    non-empty matrix. Pins that invariant separately from the no-
    filter test because it's the brittle one — a future fixture edit
    that drops the codename link would break group-filtered pact only.
    """
    from datetime import date

    await _ensure_attack_matrix_fixture(pg_session)
    await pg_session.commit()

    lazarus_id = (
        await pg_session.execute(
            sa.text("SELECT id FROM groups WHERE name = 'Lazarus Group'")
        )
    ).scalar_one()

    matrix = await compute_attack_matrix(
        pg_session,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 4, 18),
        group_ids=[int(lazarus_id)],
    )
    assert matrix["tactics"], (
        "group-filtered matrix is empty — fixture reports must be "
        "linked to the Lazarus codename via report_codenames"
    )
    assert matrix["rows"]


async def test_trend_fixture_satisfies_pact_matchers(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """``/analytics/trend`` pact: ``{buckets: eachLike({month:
    matches(YYYY-MM), count: integer})}``."""
    from datetime import date
    import re

    await _ensure_trend_fixture(pg_session)
    await pg_session.commit()

    trend = await compute_trend(
        pg_session,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 4, 18),
    )

    assert trend["buckets"], (
        "buckets is empty — /analytics/trend pact's eachLike will "
        "fail. Fixture reports must be dated inside the pact window."
    )
    month_re = re.compile(r"^\d{4}-\d{2}$")
    for bucket in trend["buckets"]:
        assert month_re.match(bucket["month"]), (
            f"month {bucket['month']!r} does not match YYYY-MM — "
            "pact regex matcher will fail"
        )
        assert (
            isinstance(bucket["count"], int) and bucket["count"] >= 1
        ), "pact: TrendBucket.count integer(≥1) under eachLike"


async def test_geo_fixture_satisfies_pact_matchers_and_includes_kp(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """``/analytics/geo`` pact: ``{countries: eachLike({iso2: string
    (min=2,max=2), count: integer})}``. Plan D7 lock: KP must be a
    plain country row — the fixture includes KP, KR, US so the pact
    fixture covers the "DPRK has no special-case field" invariant.
    """
    from datetime import date

    await _ensure_geo_fixture(pg_session)
    await pg_session.commit()

    geo = await compute_geo(
        pg_session,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 4, 18),
    )

    assert geo["countries"], (
        "countries is empty — /analytics/geo pact's eachLike will "
        "fail. Fixture incidents must be dated inside the pact window."
    )
    for country in geo["countries"]:
        assert (
            isinstance(country["iso2"], str) and len(country["iso2"]) == 2
        ), "pact: GeoCountry.iso2 is a 2-char string"
        assert (
            isinstance(country["count"], int) and country["count"] >= 1
        ), "pact: GeoCountry.count integer(≥1) under eachLike"

    iso2_codes = {c["iso2"] for c in geo["countries"]}
    assert "KP" in iso2_codes, (
        "KP must appear as a plain row — plan D7 lock says FE owns "
        "DPRK highlight and there's no BE special-case field. If this "
        "asserts false, the fixture removed KP or /analytics/geo "
        "silently filtered it."
    )


async def test_analytics_pact_fixtures_are_idempotent(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """Same contract as the dashboard idempotency test: each new
    analytics fixture must tolerate repeat invocations without UNIQUE
    violations. Also exercises the mixed case where attack_matrix +
    trend fixtures both land Lazarus + Andariel rows — the second call
    must hit the SELECT-first branch on both."""
    await _ensure_attack_matrix_fixture(pg_session)
    await _ensure_attack_matrix_fixture(pg_session)  # repeat
    await _ensure_trend_fixture(pg_session)
    await _ensure_trend_fixture(pg_session)  # repeat
    await _ensure_geo_fixture(pg_session)
    await _ensure_geo_fixture(pg_session)  # repeat
    await pg_session.commit()

    # Exactly 3 techniques (T1566/T1190/T1059) — not 6.
    tech_count = (
        await pg_session.execute(sa.text("SELECT COUNT(*) FROM techniques"))
    ).scalar_one()
    assert tech_count == 3, (
        f"expected 3 techniques after repeat seed, got {tech_count} "
        "— _ensure_technique likely lost its SELECT-first branch"
    )

    # Attack matrix has 3 reports (r1, r2, r3) linked to techniques.
    # Report r1 has TWO technique links so report_techniques row count
    # is 4 (r1→T1566, r1→T1190, r2→T1566, r3→T1059) — not 8 on repeat.
    rt_count = (
        await pg_session.execute(
            sa.text("SELECT COUNT(*) FROM report_techniques")
        )
    ).scalar_one()
    assert rt_count == 4, (
        f"expected 4 report_techniques links after repeat seed, got "
        f"{rt_count} — _link_report_technique lost ON CONFLICT"
    )

    # Geo fixture: 3 incidents with 3 distinct iso2 codes. Repeat
    # invocation must NOT double the incidents OR the country links.
    geo_inc_count = (
        await pg_session.execute(
            sa.text(
                "SELECT COUNT(*) FROM incidents WHERE title LIKE "
                "'Pact fixture — geo %'"
            )
        )
    ).scalar_one()
    assert geo_inc_count == 3, (
        f"expected 3 geo incidents, got {geo_inc_count} — "
        "_ensure_incident_with_country lost SELECT-first by title"
    )
    ic_count = (
        await pg_session.execute(
            sa.text(
                "SELECT COUNT(*) FROM incident_countries ic "
                "JOIN incidents i ON i.id = ic.incident_id "
                "WHERE i.title LIKE 'Pact fixture — geo %'"
            )
        )
    ).scalar_one()
    assert ic_count == 3, (
        f"expected 3 incident_countries links, got {ic_count} — "
        "ON CONFLICT on incident_countries lost"
    )

    # Aggregators still coherent after repeats.
    matrix = await compute_attack_matrix(pg_session)
    assert matrix["tactics"] and matrix["rows"]
    trend = await compute_trend(pg_session)
    assert trend["buckets"]
    geo = await compute_geo(pg_session)
    assert geo["countries"]
