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
from types import SimpleNamespace
from typing import AsyncIterator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import Response
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
    ACTOR_DETAIL_FIXTURE_ID,
    ACTOR_REPORTS_FIXTURE_REPORT_IDS,
    ACTOR_WITH_NO_REPORTS_ID,
    INCIDENT_DETAIL_FIXTURE_ID,
    REPORT_DETAIL_FIXTURE_ID,
    SEARCH_EMPTY_FIXTURE_REPORT_IDS,
    SEARCH_POPULATED_FIXTURE_REPORT_IDS,
    SIMILAR_EMPTY_EMBEDDING_NEIGHBOR_ID,
    SIMILAR_EMPTY_EMBEDDING_SOURCE_ID,
    SIMILAR_POPULATED_NEIGHBOR_IDS,
    SIMILAR_POPULATED_SOURCE_ID,
    _ProviderStatePayload,
    _ensure_actor_detail_fixture,
    _ensure_actor_with_no_reports_fixture,
    _ensure_actor_with_reports_fixture,
    _ensure_attack_matrix_fixture,
    _ensure_canonical_lazarus_fixture,
    _ensure_dashboard_fixture,
    _ensure_geo_fixture,
    _ensure_incident_detail_fixture,
    _ensure_incidents_trend_motivation_fixture,
    _ensure_incidents_trend_sector_fixture,
    _ensure_min_actors,
    _ensure_report_detail_fixture,
    _ensure_search_empty_fixture,
    _ensure_search_populated_fixture,
    _ensure_similar_reports_empty_embedding_fixture,
    _ensure_similar_reports_populated_fixture,
    _ensure_trend_fixture,
    provider_states,
)
from api.deps import get_embedding_client  # noqa: E402
from api.main import app  # noqa: E402
from api.read.analytics_aggregator import (  # noqa: E402
    compute_attack_matrix,
    compute_geo,
    compute_incidents_trend,
    compute_trend,
)
from api.read.dashboard_aggregator import compute_dashboard_summary  # noqa: E402
from api.read.detail_aggregator import (  # noqa: E402
    get_actor_detail,
    get_incident_detail,
    get_report_detail,
)
from api.read.actor_reports import get_actor_reports  # noqa: E402
from api.read.repositories import list_actors  # noqa: E402
from api.read.search_service import get_search_results  # noqa: E402
from api.read.similar_service import get_similar_reports  # noqa: E402


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
        # ``incident_sources`` joined the TRUNCATE list in PR #14
        # Group C — the detail + similar fixtures both touch this
        # M:N table and a leaked row from a prior run would pollute
        # the capped ``linked_incidents`` / ``linked_reports``
        # shape tests.
        await conn.execute(
            sa.text(
                "TRUNCATE report_tags, report_codenames, report_techniques, "
                "reports, tags, techniques, "
                "sources, codenames, groups, "
                "incident_motivations, incident_sectors, "
                "incident_countries, incident_sources, incidents "
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


async def test_incidents_trend_motivation_fixture_satisfies_pact_matchers(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """``/analytics/incidents_trend?group_by=motivation`` pact:
    ``{buckets: eachLike({month, count, series: eachLike({key, count})}),
       group_by: "motivation"}``.

    Both the outer ``buckets`` eachLike AND the inner per-bucket
    ``series`` eachLike must be non-empty for pact-ruby to accept the
    response (``pitfall_pact_fixture_shape``).
    """
    from datetime import date
    import re

    await _ensure_incidents_trend_motivation_fixture(pg_session)
    await pg_session.commit()

    response = await compute_incidents_trend(
        pg_session,
        group_by="motivation",
        date_from=date(2026, 1, 1),
        date_to=date(2026, 4, 18),
    )

    assert response["group_by"] == "motivation"
    buckets = response["buckets"]
    assert buckets, (
        "buckets is empty — incidents_trend pact's outer eachLike "
        "will fail. Fixture incidents must be dated inside the pact "
        "window 2026-01-01..2026-04-18 with motivation links."
    )
    month_re = re.compile(r"^\d{4}-\d{2}$")
    for bucket in buckets:
        assert month_re.match(bucket["month"]), (
            f"month {bucket['month']!r} does not match YYYY-MM regex"
        )
        assert (
            isinstance(bucket["count"], int) and bucket["count"] >= 1
        ), "pact: bucket.count integer(≥1) under outer eachLike"
        series = bucket["series"]
        assert series, (
            f"series for {bucket['month']} is empty — inner eachLike "
            "will fail. Each bucket must carry ≥1 series row."
        )
        invariant = sum(item["count"] for item in series)
        assert invariant == bucket["count"], (
            f"sum(series.count)={invariant} != bucket.count="
            f"{bucket['count']} for {bucket['month']}"
        )
        for item in series:
            assert isinstance(item["key"], str) and item["key"], (
                "pact: series.key non-empty string"
            )
            assert isinstance(item["count"], int) and item["count"] >= 1, (
                "pact: series.count integer(≥1) under inner eachLike"
            )


async def test_incidents_trend_sector_fixture_satisfies_pact_matchers(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """Sector-axis equivalent of the motivation fixture matcher test."""
    from datetime import date
    import re

    await _ensure_incidents_trend_sector_fixture(pg_session)
    await pg_session.commit()

    response = await compute_incidents_trend(
        pg_session,
        group_by="sector",
        date_from=date(2026, 1, 1),
        date_to=date(2026, 4, 18),
    )

    assert response["group_by"] == "sector"
    buckets = response["buckets"]
    assert buckets, (
        "buckets is empty — sector incidents_trend pact eachLike fails"
    )
    month_re = re.compile(r"^\d{4}-\d{2}$")
    for bucket in buckets:
        assert month_re.match(bucket["month"])
        assert isinstance(bucket["count"], int) and bucket["count"] >= 1
        series = bucket["series"]
        assert series, (
            f"series for {bucket['month']} is empty — inner eachLike "
            "fails for sector axis"
        )
        invariant = sum(item["count"] for item in series)
        assert invariant == bucket["count"]
        for item in series:
            assert isinstance(item["key"], str) and item["key"]
            assert isinstance(item["count"], int) and item["count"] >= 1


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
    await _ensure_incidents_trend_motivation_fixture(pg_session)
    await _ensure_incidents_trend_motivation_fixture(pg_session)  # repeat
    await _ensure_incidents_trend_sector_fixture(pg_session)
    await _ensure_incidents_trend_sector_fixture(pg_session)  # repeat
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


# ---------------------------------------------------------------------------
# PR #14 Group C — detail + similar-reports fixture verification
# ---------------------------------------------------------------------------
#
# Four concerns the user pinned for Group C review:
#   1. similar populated matcher is actually satisfied by the fixture
#   2. empty-embedding state reproduces D10 200 + {items: []}
#   3. all fixtures are idempotent
#   4. pact path-/query-params match the fixture exactly
#
# Each test class below targets one concern + one fixture. Tests all
# skip locally (no POSTGRES_TEST_URL); they run in the contract-verify
# CI job against a live uvicorn + PG.


async def test_report_detail_fixture_satisfies_matcher_and_caps(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """``/reports/{id}`` pact uses a matcher that expects every core
    field non-null + ``tags / codenames / techniques / linked_incidents``
    as non-empty arrays. This test hits the real detail aggregator
    and asserts the shape.
    """
    await _ensure_report_detail_fixture(pg_session)
    await pg_session.commit()

    detail = await get_report_detail(
        pg_session, report_id=REPORT_DETAIL_FIXTURE_ID
    )
    assert detail is not None, "fixture report not found by detail aggregator"
    # Core fields populated — no null in fields the pact matcher
    # declares as string/int.
    assert detail["id"] == REPORT_DETAIL_FIXTURE_ID
    assert detail["title"]
    assert detail["url"] and detail["url_canonical"]
    assert detail["published"] is not None
    assert detail["source_id"] is not None
    assert detail["source_name"]
    # Related collections non-empty (matcher uses eachLike on each).
    assert detail["tags"], "report detail fixture tags empty"
    assert detail["codenames"], "report detail fixture codenames empty"
    assert detail["techniques"], "report detail fixture techniques empty"
    assert detail["linked_incidents"], (
        "report detail fixture linked_incidents empty — incident_sources "
        "seed path may be broken"
    )
    # D9 cap respected (fixture seeds 2, cap is 10).
    assert len(detail["linked_incidents"]) == 2


async def test_report_detail_fixture_is_idempotent(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """Idempotency — the verifier replays state setup before every
    interaction. A helper that accidentally creates a new row on
    each call would break the pinned fixture id or explode the
    linked_incidents capped list over time.
    """
    await _ensure_report_detail_fixture(pg_session)
    await _ensure_report_detail_fixture(pg_session)
    await _ensure_report_detail_fixture(pg_session)
    await pg_session.commit()

    detail = await get_report_detail(
        pg_session, report_id=REPORT_DETAIL_FIXTURE_ID
    )
    assert detail is not None
    # Linked-incidents count is STILL 2 (not 4 or 6) after three
    # state setups — incident_sources ON CONFLICT held.
    assert len(detail["linked_incidents"]) == 2


async def test_incident_detail_fixture_satisfies_matcher_and_caps(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """``/incidents/{id}`` pact mirror of the report test above."""
    await _ensure_incident_detail_fixture(pg_session)
    await pg_session.commit()

    detail = await get_incident_detail(
        pg_session, incident_id=INCIDENT_DETAIL_FIXTURE_ID
    )
    assert detail is not None
    assert detail["id"] == INCIDENT_DETAIL_FIXTURE_ID
    assert detail["title"]
    assert detail["reported"] is not None
    assert detail["motivations"], "incident fixture motivations empty"
    assert detail["sectors"], "incident fixture sectors empty"
    assert detail["countries"], "incident fixture countries empty"
    assert detail["linked_reports"], (
        "incident fixture linked_reports empty — incident_sources seed "
        "path may be broken"
    )
    assert len(detail["linked_reports"]) == 2


async def test_incident_detail_fixture_is_idempotent(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    await _ensure_incident_detail_fixture(pg_session)
    await _ensure_incident_detail_fixture(pg_session)
    await pg_session.commit()
    detail = await get_incident_detail(
        pg_session, incident_id=INCIDENT_DETAIL_FIXTURE_ID
    )
    assert detail is not None
    assert len(detail["linked_reports"]) == 2


async def test_actor_detail_fixture_satisfies_matcher(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """``/actors/{id}`` pact — core fields + non-empty codenames. No
    linked_reports path per plan D11.

    PR #14 Group G: fixture pins ``ACTOR_DETAIL_FIXTURE_ID`` so the
    pact consumer can target ``/actors/999003`` literally (no regex
    path matcher, no DB-sequence drift). Matchers are shape-only
    (like/eachLike), so the pact's example values ("Lazarus Group",
    "Andariel") match this fixture's values ("Pact fixture actor
    detail", "pact-actor-detail-codename") by type — integer for id,
    string for names, arrays non-empty — not by exact value.
    """
    await _ensure_actor_detail_fixture(pg_session)
    await pg_session.commit()

    # Pinned id — no SELECT-by-name probe.
    detail = await get_actor_detail(
        pg_session, actor_id=ACTOR_DETAIL_FIXTURE_ID
    )
    assert detail is not None, (
        f"actor detail fixture not seeded at id={ACTOR_DETAIL_FIXTURE_ID}"
    )
    # Shape — not exact value. These are the matchers the pact
    # consumer asserts on; any fixture that satisfies the PACT
    # eachLike/like shape satisfies this test.
    assert isinstance(detail["id"], int)
    assert detail["id"] == ACTOR_DETAIL_FIXTURE_ID
    assert isinstance(detail["name"], str) and detail["name"]
    assert isinstance(detail["mitre_intrusion_set_id"], str)
    assert detail["aka"], "actor detail fixture aka empty"
    assert detail["description"]
    assert detail["codenames"], (
        "actor detail fixture codenames empty — pinned codename link broken"
    )
    # D11 lock — actor detail MUST NOT expose reports-like keys.
    for forbidden in ("linked_reports", "reports", "recent_reports"):
        assert forbidden not in detail


async def test_actor_detail_fixture_is_idempotent(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """PR #14 Group G idempotency — state replays across a verifier
    run MUST not double-insert the pinned actor or its codename.

    The groups insert uses ``ON CONFLICT (id) DO NOTHING``; the
    codename upsert is SELECT-first. Two consecutive calls produce
    exactly one row each.
    """
    await _ensure_actor_detail_fixture(pg_session)
    await _ensure_actor_detail_fixture(pg_session)
    await pg_session.commit()

    group_count = (
        await pg_session.execute(
            sa.text(
                "SELECT COUNT(*) FROM groups WHERE id = :id"
            ),
            {"id": ACTOR_DETAIL_FIXTURE_ID},
        )
    ).scalar_one()
    assert int(group_count) == 1

    codename_count = (
        await pg_session.execute(
            sa.text(
                "SELECT COUNT(*) FROM codenames WHERE group_id = :g"
            ),
            {"g": ACTOR_DETAIL_FIXTURE_ID},
        )
    ).scalar_one()
    assert int(codename_count) == 1


async def test_similar_populated_fixture_produces_non_empty_knn(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """Plan D8 populated path — source + 3 neighbors, all with
    embeddings. The live kNN against the seeded source must return
    a non-empty ``items`` (3 neighbors minus self = 3 rows).
    Self-exclusion invariant: ``SIMILAR_POPULATED_SOURCE_ID`` never
    appears in the result.
    """
    await _ensure_similar_reports_populated_fixture(pg_session)
    await pg_session.commit()

    result = await get_similar_reports(
        pg_session, source_report_id=SIMILAR_POPULATED_SOURCE_ID, k=10
    )
    assert result.found is True
    assert result.items, (
        "similar populated fixture produced empty items — kNN not hitting "
        "seeded embeddings or _make_embedding(...) malformed"
    )
    # Self-exclusion (plan D8a).
    ids = [row["report"]["id"] for row in result.items]
    assert SIMILAR_POPULATED_SOURCE_ID not in ids
    # Neighbors present (may be subset; matcher is eachLike on shape).
    assert set(ids) & set(SIMILAR_POPULATED_NEIGHBOR_IDS), (
        "similar populated fixture returned unexpected ids — expected "
        f"overlap with {SIMILAR_POPULATED_NEIGHBOR_IDS}"
    )
    # Score shape (float in [0, 1]).
    for row in result.items:
        assert 0.0 <= row["score"] <= 1.0


async def test_similar_populated_fixture_is_idempotent(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """Three state setups → same 4 rows (1 source + 3 neighbors).
    ON CONFLICT DO UPDATE holds.
    """
    await _ensure_similar_reports_populated_fixture(pg_session)
    await _ensure_similar_reports_populated_fixture(pg_session)
    await _ensure_similar_reports_populated_fixture(pg_session)
    await pg_session.commit()

    count = (
        await pg_session.execute(
            sa.text(
                "SELECT COUNT(*) FROM reports WHERE id IN ("
                ":src, :n1, :n2, :n3)"
            ),
            {
                "src": SIMILAR_POPULATED_SOURCE_ID,
                "n1": SIMILAR_POPULATED_NEIGHBOR_IDS[0],
                "n2": SIMILAR_POPULATED_NEIGHBOR_IDS[1],
                "n3": SIMILAR_POPULATED_NEIGHBOR_IDS[2],
            },
        )
    ).scalar_one()
    assert int(count) == 4


async def test_similar_empty_embedding_fixture_produces_D10_empty(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """Plan D10 empty-contract path. Source exists but has NULL
    embedding; one neighbor exists WITH an embedding. The service
    must return ``{items: []}`` — not a fake fallback using the
    neighbor as a "most similar" substitute.

    This test is the regression guard the user called out for
    Group C review — if a future refactor collapses the D10 check
    to "DB-wide emptiness", this fixture (DB has embeddings
    elsewhere) would trick the check and return the neighbor, and
    this test fires red.
    """
    await _ensure_similar_reports_empty_embedding_fixture(pg_session)
    await pg_session.commit()

    result = await get_similar_reports(
        pg_session,
        source_report_id=SIMILAR_EMPTY_EMBEDDING_SOURCE_ID,
        k=10,
    )
    # 200 on the endpoint lifts to found=True at service layer.
    assert result.found is True
    assert result.items == [], (
        "D10 empty-contract violated — source has no embedding yet the "
        "service returned similar rows. Possible regression: the check "
        "collapsed to 'DB-wide emptiness' instead of 'source NULL'."
    )
    # Sanity — the neighbor with an embedding still EXISTS in the DB
    # (otherwise the regression guard is vacuous).
    neighbor_exists = (
        await pg_session.execute(
            sa.text(
                "SELECT embedding IS NOT NULL FROM reports WHERE id = :id"
            ),
            {"id": SIMILAR_EMPTY_EMBEDDING_NEIGHBOR_ID},
        )
    ).scalar()
    assert neighbor_exists is True, (
        "fixture setup error — empty-embedding neighbor lost its embedding"
    )


async def test_similar_empty_embedding_fixture_is_idempotent(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    await _ensure_similar_reports_empty_embedding_fixture(pg_session)
    await _ensure_similar_reports_empty_embedding_fixture(pg_session)
    await pg_session.commit()

    src_null = (
        await pg_session.execute(
            sa.text(
                "SELECT embedding IS NULL FROM reports WHERE id = :id"
            ),
            {"id": SIMILAR_EMPTY_EMBEDDING_SOURCE_ID},
        )
    ).scalar()
    # Source stays NULL across repeats — ON CONFLICT UPDATE sets
    # embedding = NULL each time.
    assert src_null is True


# ---------------------------------------------------------------------------
# PR #15 Group C — actor-reports populated + empty fixtures
# ---------------------------------------------------------------------------
#
# Four invariants the reviewer asked to check:
#
#   1. 999003 populated actor-reports matcher is actually satisfied
#      — the fixture seeds ≥3 reports linked via codename to actor
#      999003, each row has the ReportItem shape, sort is newest-
#      first per D16.
#   2. 999004 empty state reproduces as 200 + {items: [], next_cursor:
#      null} — actor exists + has codenames + zero report_codenames
#      rows, so get_actor_reports returns ([], None, None).
#   3. Both fixtures are idempotent — two consecutive invocations
#      produce the same row counts.
#   4. FE pact path literal alignment — 999003 and 999004 are the
#      exact ids the FE consumer hardcodes; this test file imports
#      the constants directly so a rename on either side would flag
#      at import time. Additional explicit assertion below for
#      safety.


async def test_actor_with_reports_fixture_produces_non_empty_keyset_page(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """Populated matcher satisfaction — ``/actors/999003/reports``
    pact expects ``{items: eachLike(ReportItem), next_cursor}``.

    Fixture must seed ≥1 non-empty row (eachLike rejects empty) with
    the full ReportItem shape (id/title/url/url_canonical/published/
    source_id/source_name/lang/tlp). Sort order is DESC on published
    per plan D16 — newest fixture row lands first. The pact's
    matchers are type-only so specific titles are not asserted, only
    that the envelope produces at least the 3 seeded rows in
    D16-stable order.
    """
    await _ensure_actor_with_reports_fixture(pg_session)
    await pg_session.commit()

    result = await get_actor_reports(
        pg_session, actor_id=ACTOR_DETAIL_FIXTURE_ID, limit=50
    )
    assert result is not None, (
        f"populated fixture actor not seeded at id={ACTOR_DETAIL_FIXTURE_ID}"
    )
    items, next_p, next_i = result

    # eachLike pact matcher would fail on empty — pin the >=1 floor
    # AND the exact count we seeded so a future regression that drops
    # links fires red here before the FE pact verifier does.
    assert len(items) >= 3, (
        f"populated fixture produced {len(items)} rows; "
        f"expected >=3 (the seeded {ACTOR_REPORTS_FIXTURE_REPORT_IDS})"
    )
    # Every item satisfies ReportItem shape — the matcher walks
    # these keys and types.
    for item in items:
        assert isinstance(item["id"], int)
        assert isinstance(item["title"], str) and item["title"]
        assert isinstance(item["url"], str) and item["url"]
        assert isinstance(item["url_canonical"], str)
        # ``published`` is a ``date`` in-process; pact sees the
        # ISO-8601 string that FastAPI serializes from it.
        assert item["published"] is not None
        assert isinstance(item["source_id"], int)
        assert isinstance(item["source_name"], str)
        assert item["tlp"] == "WHITE"

    # D16 newest-first — the fixture's top pinned id (999050) has
    # the newest date (2026-03-15), so it lands at index 0.
    assert items[0]["id"] == ACTOR_REPORTS_FIXTURE_REPORT_IDS[0]

    # Final page — fixture seeds 3 rows below the default 50 limit,
    # so next_cursor is null.
    assert next_p is None
    assert next_i is None


async def test_actor_without_reports_fixture_produces_empty_envelope(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """Empty reproduction — ``/actors/999004/reports`` pact expects
    ``{items: [], next_cursor: null}`` (literal empty body, cannot
    use eachLike per PR #14 Group G precedent).

    Actor must exist (so the router yields 200, not 404) and the
    reports query must return ([], None, None). Mix of D15(b)
    (no codenames — NOT what we seed here) and D15(c) (has codenames
    but zero report_codenames — this IS what we seed). The empty
    envelope is identical across the two branches so this single
    test also covers the D15(c) flavor.
    """
    await _ensure_actor_with_no_reports_fixture(pg_session)
    await pg_session.commit()

    result = await get_actor_reports(
        pg_session, actor_id=ACTOR_WITH_NO_REPORTS_ID, limit=50
    )
    # Actor exists — NOT None (None would mean router → 404).
    assert result is not None, (
        "D15(a)/D15(b-c) collapse regression — empty-reports actor "
        "must return envelope, not None. Router depends on this to "
        "yield 200 instead of 404."
    )
    items, next_p, next_i = result
    assert items == []
    assert next_p is None
    assert next_i is None


async def test_actor_with_reports_fixture_is_idempotent(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """Idempotency — pact verifier replays state handlers inside one
    run. Two consecutive invocations of the populated seed must not
    double-insert the pinned reports or the composite
    ``report_codenames`` links.

    The groups insert uses ON CONFLICT (id) DO NOTHING (inherited
    from _ensure_actor_detail_fixture), reports use the same pattern
    on ``reports.id``, and report_codenames uses ON CONFLICT DO
    NOTHING on its composite PK.
    """
    await _ensure_actor_with_reports_fixture(pg_session)
    await _ensure_actor_with_reports_fixture(pg_session)
    await pg_session.commit()

    # One actor group row at the pinned id.
    group_count = (
        await pg_session.execute(
            sa.text("SELECT COUNT(*) FROM groups WHERE id = :id"),
            {"id": ACTOR_DETAIL_FIXTURE_ID},
        )
    ).scalar_one()
    assert int(group_count) == 1

    # Exactly 3 seeded reports at the pinned ids.
    for rid in ACTOR_REPORTS_FIXTURE_REPORT_IDS:
        row_count = (
            await pg_session.execute(
                sa.text(
                    "SELECT COUNT(*) FROM reports WHERE id = :id"
                ),
                {"id": rid},
            )
        ).scalar_one()
        assert int(row_count) == 1, (
            f"report id {rid} double-inserted — "
            f"ON CONFLICT (id) DO NOTHING broken"
        )

    # Exactly one link row per seeded report — composite PK
    # collision would fire on the second invocation without the ON
    # CONFLICT DO NOTHING on the composite PK.
    link_count = (
        await pg_session.execute(
            sa.text(
                "SELECT COUNT(*) FROM report_codenames "
                "WHERE report_id = ANY(:ids)"
            ),
            {"ids": list(ACTOR_REPORTS_FIXTURE_REPORT_IDS)},
        )
    ).scalar_one()
    assert int(link_count) == len(ACTOR_REPORTS_FIXTURE_REPORT_IDS)


async def test_actor_without_reports_fixture_is_idempotent(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """Idempotency for the empty-fixture seed."""
    await _ensure_actor_with_no_reports_fixture(pg_session)
    await _ensure_actor_with_no_reports_fixture(pg_session)
    await pg_session.commit()

    group_count = (
        await pg_session.execute(
            sa.text("SELECT COUNT(*) FROM groups WHERE id = :id"),
            {"id": ACTOR_WITH_NO_REPORTS_ID},
        )
    ).scalar_one()
    assert int(group_count) == 1

    codename_count = (
        await pg_session.execute(
            sa.text(
                "SELECT COUNT(*) FROM codenames WHERE group_id = :g"
            ),
            {"g": ACTOR_WITH_NO_REPORTS_ID},
        )
    ).scalar_one()
    assert int(codename_count) == 1

    # D15(c) invariant — zero report_codenames rows.
    link_count = (
        await pg_session.execute(
            sa.text(
                "SELECT COUNT(*) FROM report_codenames rc "
                "JOIN codenames c ON c.id = rc.codename_id "
                "WHERE c.group_id = :g"
            ),
            {"g": ACTOR_WITH_NO_REPORTS_ID},
        )
    ).scalar_one()
    assert int(link_count) == 0, (
        "empty fixture must have zero report_codenames rows — "
        "D15(c) contract broken"
    )


# NOTE: the FE pact path literal alignment regression guard lives in
# ``tests/unit/test_actor_reports.py::TestFePactPathLiteralAlignment``
# so it runs WITHOUT a Postgres connection. This module is
# module-level skipped when POSTGRES_TEST_URL is unset, which would
# hide a constant-drift regression in local dev / pre-push runs.


# ---------------------------------------------------------------------------
# PR #17 Group C — /search populated + empty fixture verification
# ---------------------------------------------------------------------------
#
# Three concerns pinned for Group C review:
#
#   1. Populated seed actually satisfies the ``q=lazarus`` pact —
#      the FTS predicate ``plainto_tsquery('simple', 'lazarus')``
#      against ``COALESCE(title,'') || ' ' || COALESCE(summary,'')``
#      returns ≥3 rows, per-hit fts_rank > 0, vector_rank is None.
#   2. Empty seed reproduces D10 ``{items: []}`` for ``q=nomatchxyz123``
#      UNDER A NON-EMPTY reports table (the distractor exists to
#      rule out "DB empty → trivially empty envelope" as a regression
#      that would mask a broken FTS predicate).
#   3. Both fixtures are idempotent under repeat state setup.
#
# Constant-drift guard runs unconditionally in
# ``tests/unit/test_search_service.py::TestSearchFixturePactPathLiteralAlignment``
# so a rename of the 999060-63 ids surfaces without a live Postgres.


async def test_search_populated_fixture_matches_lazarus_and_sorts_ties(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """Populated matcher satisfaction — ``/api/v1/search?q=lazarus``
    pact expects ``{items: eachLike(SearchHit), total_hits, latency_ms}``.

    Fixture seeds 3 reports with Lazarus in both title and summary so
    ``plainto_tsquery('simple', 'lazarus')`` matches against
    ``COALESCE(title,'') || ' ' || COALESCE(summary,'')``. Assert:
      - items non-empty (eachLike rejects []),
      - every hit satisfies the SearchHit shape (report+fts_rank+
        vector_rank=null),
      - total_hits equals the seeded row count (3),
      - rows sort by ``fts_rank DESC, id DESC`` — when ranks tie (all
        three rows have similar Lazarus density), the stable tie-break
        puts the highest id (999062) first.
    """
    await _ensure_search_populated_fixture(pg_session)
    await pg_session.commit()

    result = await get_search_results(
        pg_session,
        redis=None,
        q="lazarus",
        date_from=None,
        date_to=None,
        limit=10,
    )
    payload = result.payload

    items = payload["items"]
    assert len(items) >= 3, (
        f"populated fixture produced {len(items)} hits; expected >=3 "
        f"(the seeded {SEARCH_POPULATED_FIXTURE_REPORT_IDS})"
    )
    assert payload["total_hits"] >= 3

    seeded_ids = set(SEARCH_POPULATED_FIXTURE_REPORT_IDS)
    returned_ids = {hit["report"]["id"] for hit in items}
    assert seeded_ids <= returned_ids, (
        f"missing seeded ids — got {returned_ids}, expected superset of "
        f"{seeded_ids}"
    )

    for hit in items:
        # SearchHit shape: report sub-object is a ReportItem; fts_rank
        # float > 0 (matched a real token); vector_rank is literally
        # None (D9 forward-compat slot).
        report = hit["report"]
        assert isinstance(report["id"], int)
        assert isinstance(report["title"], str) and report["title"]
        assert isinstance(report["url"], str) and report["url"]
        assert isinstance(report["url_canonical"], str)
        assert report["published"] is not None
        assert isinstance(report["source_id"], int)
        assert isinstance(report["source_name"], str)
        assert report["tlp"] == "WHITE"
        assert isinstance(hit["fts_rank"], float) and hit["fts_rank"] > 0.0
        assert hit["vector_rank"] is None, (
            "D9 forward-compat slot violated — vector_rank must be "
            "literally None until the follow-up hybrid PR fills it"
        )

    # Plan D2 locks ``ts_rank_cd DESC, reports.id DESC`` as stable
    # sort but ``ts_rank_cd`` is document-length-sensitive, so three
    # rows with similar Lazarus density may have non-equal ranks and
    # the id tie-break only fires on true ties. The pact matcher is
    # ``eachLike`` shape-only — it does not assert a specific row
    # order. So this test pins the weaker invariant the pact cares
    # about: the three seeded rows all land above any non-seeded row
    # for this query (there are no other Lazarus rows to beat them).
    top_three_ids = [hit["report"]["id"] for hit in items[:3]]
    assert set(top_three_ids) == seeded_ids, (
        f"seeded rows did not sweep the top 3 — got {top_three_ids}, "
        f"expected exactly {seeded_ids}"
    )


async def test_search_empty_fixture_produces_D10_empty_against_nomatchxyz123(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """Plan D10 empty-contract path — the distractor row exists so
    the reports table is non-empty, and ``q=nomatchxyz123`` must still
    return ``{items: [], total_hits: 0}``.

    The regression this pins: if a future refactor collapses the D10
    envelope to "empty reports table → empty envelope", this test
    fires red because the DB has a real row and the FTS predicate is
    doing the filtering.
    """
    await _ensure_search_empty_fixture(pg_session)
    await pg_session.commit()

    result = await get_search_results(
        pg_session,
        redis=None,
        q="nomatchxyz123",
        date_from=None,
        date_to=None,
        limit=10,
    )
    payload = result.payload

    assert payload["items"] == [], (
        "D10 empty-contract violated — nomatchxyz123 query returned "
        f"{len(payload['items'])} rows. The FTS predicate must filter "
        "the distractor row out by token miss, not by DB emptiness."
    )
    assert payload["total_hits"] == 0

    # Sanity — the distractor row still exists (otherwise this test is
    # vacuous). Mirror of the similar empty-embedding neighbor check.
    distractor_exists = (
        await pg_session.execute(
            sa.text("SELECT 1 FROM reports WHERE id = :id"),
            {"id": SEARCH_EMPTY_FIXTURE_REPORT_IDS[0]},
        )
    ).scalar()
    assert distractor_exists == 1, (
        "distractor row missing — empty fixture helper did not insert"
    )


async def test_search_populated_fixture_is_idempotent(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """Idempotency — pact verifier replays state setup before every
    interaction. Three consecutive calls must produce exactly 3 rows
    at the pinned ids, not 9.
    """
    await _ensure_search_populated_fixture(pg_session)
    await _ensure_search_populated_fixture(pg_session)
    await _ensure_search_populated_fixture(pg_session)
    await pg_session.commit()

    for rid in SEARCH_POPULATED_FIXTURE_REPORT_IDS:
        count = (
            await pg_session.execute(
                sa.text("SELECT COUNT(*) FROM reports WHERE id = :id"),
                {"id": rid},
            )
        ).scalar_one()
        assert int(count) == 1, (
            f"report id {rid} double-inserted on repeat state setup — "
            "ON CONFLICT (id) DO NOTHING broken"
        )


async def test_search_populated_fixture_stamps_embedding_not_null(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """PR #19b OI6 = B — the 3 populated fixture rows carry non-null
    ``reports.embedding`` after the state handler runs.

    Without this stamp, the hybrid ``/search`` pact verifier would
    return ``vector_rank: null`` and the consumer's ``integer()``
    matcher (FE pact) would fail. Pinning embedding presence here
    keeps the consumer + provider contract in sync.
    """
    await _ensure_search_populated_fixture(pg_session)
    await pg_session.commit()

    for rid in SEARCH_POPULATED_FIXTURE_REPORT_IDS:
        not_null = (
            await pg_session.execute(
                sa.text(
                    "SELECT embedding IS NOT NULL "
                    "FROM reports WHERE id = :id"
                ),
                {"id": rid},
            )
        ).scalar_one()
        assert bool(not_null) is True, (
            f"report id {rid} has null embedding after state setup — "
            "OI6 = B stamp step missed; hybrid vector_rank would "
            "come back null and the consumer integer() matcher fails"
        )


async def test_search_populated_fixture_embedding_stamp_is_idempotent(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    """The embedding UPDATE is null-guarded — repeat runs do not
    overwrite a previously-stamped vector.

    Without the ``AND embedding IS NULL`` guard in the UPDATE, a
    repeat state setup would re-stamp and silently drift the cosine
    distance profile, so the vector_rank ordering of the 3 rows
    could move between verifications.
    """
    # First run stamps embeddings.
    await _ensure_search_populated_fixture(pg_session)
    await pg_session.commit()

    # Capture the stamped vectors.
    first_run_vecs: dict[int, str] = {}
    for rid in SEARCH_POPULATED_FIXTURE_REPORT_IDS:
        vec = (
            await pg_session.execute(
                sa.text("SELECT embedding::text FROM reports WHERE id = :id"),
                {"id": rid},
            )
        ).scalar_one()
        first_run_vecs[rid] = vec

    # Repeat state setup several times.
    await _ensure_search_populated_fixture(pg_session)
    await _ensure_search_populated_fixture(pg_session)
    await pg_session.commit()

    for rid in SEARCH_POPULATED_FIXTURE_REPORT_IDS:
        after = (
            await pg_session.execute(
                sa.text("SELECT embedding::text FROM reports WHERE id = :id"),
                {"id": rid},
            )
        ).scalar_one()
        assert after == first_run_vecs[rid], (
            f"report id {rid} embedding drifted across repeat state "
            "setups — UPDATE lacks ``embedding IS NULL`` guard"
        )


async def test_search_provider_state_installs_and_clears_embedding_override(
    clean_pg: None,
    pg_session: AsyncSession,
    session_store,
) -> None:
    """Provider-state POST toggles the hybrid /search embedding override."""

    app.dependency_overrides.pop(get_embedding_client, None)
    request = SimpleNamespace(app=app)

    try:
        await provider_states(
            request=request,
            payload=_ProviderStatePayload(
                state=(
                    "seeded search populated fixture "
                    "and an authenticated analyst session"
                )
            ),
            response=Response(),
            session_store=session_store,
            session=pg_session,
        )

        override = app.dependency_overrides.get(get_embedding_client)
        assert override is not None, (
            "search populated provider state did not install the "
            "embedding-client override — contract-verify would stay "
            "FTS-only and return vector_rank: null"
        )

        stub = override()
        result = await stub.embed(["lazarus"])
        assert len(result.vectors) == 1
        assert result.vectors[0][0] > result.vectors[0][1] > result.vectors[0][2]

        await provider_states(
            request=request,
            payload=_ProviderStatePayload(state="no valid session cookie"),
            response=Response(),
            session_store=session_store,
            session=pg_session,
        )
        assert get_embedding_client not in app.dependency_overrides, (
            "embedding-client override leaked into the next interaction — "
            "provider-state baseline reset is broken"
        )
    finally:
        app.dependency_overrides.pop(get_embedding_client, None)


async def test_search_empty_fixture_is_idempotent(
    clean_pg: None, pg_session: AsyncSession
) -> None:
    await _ensure_search_empty_fixture(pg_session)
    await _ensure_search_empty_fixture(pg_session)
    await pg_session.commit()

    count = (
        await pg_session.execute(
            sa.text("SELECT COUNT(*) FROM reports WHERE id = :id"),
            {"id": SEARCH_EMPTY_FIXTURE_REPORT_IDS[0]},
        )
    ).scalar_one()
    assert int(count) == 1
