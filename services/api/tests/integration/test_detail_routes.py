"""Integration tests for PR #14 Group A detail endpoints.

Covers the HTTP-layer contract for the 3 new routes:
- ``GET /api/v1/reports/{report_id}``
- ``GET /api/v1/incidents/{incident_id}``
- ``GET /api/v1/actors/{actor_id}``

Correctness of the SQL joins + D9 caps lives in
``tests/unit/test_detail_aggregator.py``; this file focuses on:

1. **404 on unknown id** (per entity) — body uses ``{"detail": "..."}``
   so the FE error branch matches both FastAPI-default path-param
   failures and our hand-rolled 404 JSON.
2. **422 on non-integer path param** — FastAPI's own path-param
   validation kicks in before our handler runs (plan D12 uniform 422).
3. **Happy path response shape** matches the DTO's OpenAPI example.
4. **bidirectional navigation** via ``incident_sources`` works end-to-
   end through the HTTP layer.
5. **Actor detail does NOT leak report_codenames** — response shape
   has no reports-like key even when the DB has report_codenames rows.
"""

from __future__ import annotations

import datetime as dt
from typing import AsyncIterator

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

from api.tables import (
    codenames_table,
    groups_table,
    incident_sources_table,
    incidents_table,
    metadata,
    report_codenames_table,
    reports_table,
    sources_table,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def detail_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def detail_client(
    detail_engine: AsyncEngine, session_store, fake_redis
) -> AsyncIterator[AsyncClient]:
    from api.auth.session import get_session_store
    from api.db import get_db
    from api.main import app

    sessionmaker = async_sessionmaker(detail_engine, expire_on_commit=False)

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


async def _cookie(make_session_cookie, role: str = "analyst") -> str:
    return await make_session_cookie(roles=[role])


async def _seed_source(engine: AsyncEngine, name: str = "Mandiant") -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(sources_table)
            .values(name=name, type="vendor")
            .returning(sources_table.c.id)
        )
        out = row.scalar_one()
        await s.commit()
        return out


async def _seed_report(
    engine: AsyncEngine,
    *,
    title: str,
    source_id: int,
    published: dt.date = dt.date(2026, 3, 15),
) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(reports_table)
            .values(
                title=title,
                url=f"https://ex.test/{title}",
                url_canonical=f"https://ex.test/{title}",
                sha256_title=f"sha-{title}",
                source_id=source_id,
                published=published,
                tlp="WHITE",
            )
            .returning(reports_table.c.id)
        )
        out = row.scalar_one()
        await s.commit()
        return out


async def _seed_incident(
    engine: AsyncEngine,
    *,
    title: str,
    reported: dt.date | None = dt.date(2024, 5, 2),
) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(incidents_table)
            .values(title=title, reported=reported)
            .returning(incidents_table.c.id)
        )
        out = row.scalar_one()
        await s.commit()
        return out


async def _seed_group(engine: AsyncEngine, *, name: str = "Lazarus Group") -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(groups_table)
            .values(
                name=name,
                mitre_intrusion_set_id="G0032",
                aka=["APT38"],
                description="dprk",
            )
            .returning(groups_table.c.id)
        )
        out = row.scalar_one()
        await s.commit()
        return out


async def _link_incident_source(
    engine: AsyncEngine, *, incident_id: int, report_id: int
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await s.execute(
            sa.insert(incident_sources_table).values(
                incident_id=incident_id, report_id=report_id
            )
        )
        await s.commit()


# ---------------------------------------------------------------------------
# 404 per entity
# ---------------------------------------------------------------------------


class Test404:
    async def test_report_unknown_id(
        self, detail_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await detail_client.get(
            "/api/v1/reports/99999", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 404
        assert resp.json() == {"detail": "report not found"}

    async def test_incident_unknown_id(
        self, detail_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await detail_client.get(
            "/api/v1/incidents/99999", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 404
        assert resp.json() == {"detail": "incident not found"}

    async def test_actor_unknown_id(
        self, detail_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await detail_client.get(
            "/api/v1/actors/99999", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 404
        assert resp.json() == {"detail": "actor not found"}


# ---------------------------------------------------------------------------
# 422 on malformed path param
# ---------------------------------------------------------------------------


class Test422:
    async def test_report_non_integer_id_is_422(
        self, detail_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await detail_client.get(
            "/api/v1/reports/not-a-number",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422

    async def test_incident_non_integer_id_is_422(
        self, detail_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await detail_client.get(
            "/api/v1/incidents/abc",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422

    async def test_actor_non_integer_id_is_422(
        self, detail_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await detail_client.get(
            "/api/v1/actors/xyz",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Happy path — shape matches DTO + OpenAPI example contract
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_report_detail_matches_dto_shape(
        self,
        detail_client: AsyncClient,
        make_session_cookie,
        detail_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(detail_engine)
        r_id = await _seed_report(detail_engine, title="r1", source_id=src)
        cookie = await _cookie(make_session_cookie)
        resp = await detail_client.get(
            f"/api/v1/reports/{r_id}",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        # Every DTO field present — including the empty lists.
        expected_keys = {
            "id", "title", "url", "url_canonical", "published",
            "source_id", "source_name", "lang", "tlp", "summary",
            "reliability", "credibility", "tags", "codenames",
            "techniques", "linked_incidents",
        }
        assert set(body.keys()) == expected_keys
        assert body["tags"] == []
        assert body["codenames"] == []
        assert body["techniques"] == []
        assert body["linked_incidents"] == []

    async def test_incident_detail_matches_dto_shape(
        self,
        detail_client: AsyncClient,
        make_session_cookie,
        detail_engine: AsyncEngine,
    ) -> None:
        i_id = await _seed_incident(detail_engine, title="i1")
        cookie = await _cookie(make_session_cookie)
        resp = await detail_client.get(
            f"/api/v1/incidents/{i_id}",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        expected_keys = {
            "id", "reported", "title", "description", "est_loss_usd",
            "attribution_confidence", "motivations", "sectors",
            "countries", "linked_reports",
        }
        assert set(body.keys()) == expected_keys

    async def test_actor_detail_matches_dto_shape_no_reports_key(
        self,
        detail_client: AsyncClient,
        make_session_cookie,
        detail_engine: AsyncEngine,
    ) -> None:
        g_id = await _seed_group(detail_engine)
        cookie = await _cookie(make_session_cookie)
        resp = await detail_client.get(
            f"/api/v1/actors/{g_id}",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        expected_keys = {
            "id", "name", "mitre_intrusion_set_id", "aka",
            "description", "codenames",
        }
        assert set(body.keys()) == expected_keys
        # D11 lock: no linked_reports key surfaces even when
        # report_codenames seed exists upstream.
        for forbidden in ("linked_reports", "reports", "recent_reports"):
            assert forbidden not in body


# ---------------------------------------------------------------------------
# D11 positive-path — incident ↔ report bidirectional
# ---------------------------------------------------------------------------


class TestIncidentSourcesBidirectional:
    async def test_report_shows_incident_and_incident_shows_report(
        self,
        detail_client: AsyncClient,
        make_session_cookie,
        detail_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(detail_engine)
        r_id = await _seed_report(detail_engine, title="anchor-r", source_id=src)
        i_id = await _seed_incident(detail_engine, title="anchor-i")
        await _link_incident_source(
            detail_engine, incident_id=i_id, report_id=r_id
        )
        cookie = await _cookie(make_session_cookie)

        r_resp = await detail_client.get(
            f"/api/v1/reports/{r_id}", cookies={"dprk_cti_session": cookie}
        )
        i_resp = await detail_client.get(
            f"/api/v1/incidents/{i_id}", cookies={"dprk_cti_session": cookie}
        )
        assert r_resp.status_code == 200
        assert i_resp.status_code == 200
        r_body = r_resp.json()
        i_body = i_resp.json()
        # Exactly-one-row check both directions.
        assert [row["id"] for row in r_body["linked_incidents"]] == [i_id]
        assert [row["id"] for row in i_body["linked_reports"]] == [r_id]


# ---------------------------------------------------------------------------
# D11 negative-path — actor detail does NOT leak report_codenames data
# ---------------------------------------------------------------------------


class TestActorDetailNoReportCodenamesLeak:
    async def test_seeded_report_codenames_link_does_not_surface_in_actor_detail(
        self,
        detail_client: AsyncClient,
        make_session_cookie,
        detail_engine: AsyncEngine,
    ) -> None:
        """If a future refactor adds ``linked_reports`` to ActorDetail
        by traversing report_codenames, this test fails immediately.
        """
        src = await _seed_source(detail_engine)
        r_id = await _seed_report(
            detail_engine, title="mentions-lazarus", source_id=src
        )
        g_id = await _seed_group(detail_engine)
        async with AsyncSession(detail_engine) as s:
            cn_row = await s.execute(
                sa.insert(codenames_table)
                .values(name="Andariel", group_id=g_id)
                .returning(codenames_table.c.id)
            )
            c_id = cn_row.scalar_one()
            await s.execute(
                sa.insert(report_codenames_table).values(
                    report_id=r_id, codename_id=c_id
                )
            )
            await s.commit()

        cookie = await _cookie(make_session_cookie)
        resp = await detail_client.get(
            f"/api/v1/actors/{g_id}", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "linked_reports" not in body
        assert "reports" not in body
        # Core codenames list DOES include the seeded codename — that
        # is group-owned data, not traversal through report_codenames.
        assert body["codenames"] == ["Andariel"]
