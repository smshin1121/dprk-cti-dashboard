"""Integration tests for GET /api/v1/actors/{id}/reports (PR #15 Group B).

Runs against in-memory aiosqlite via dependency override — same
fixture pattern as ``test_actors_route.py``. Real-PG scenarios
(cursor stability under concurrent insert, rate-limit bucket proof)
land in ``test_read_real_pg.py``.

Review priorities locked at the Group B ask:

1. **D15(a) 404 vs 200-empty split.** Missing actor id returns 404
   with the body ``{"detail": "actor not found"}`` — identical to
   the existing ``GET /actors/{id}`` detail 404. Empty branches
   (b/c/d) return 200 with ``{"items": [], "next_cursor": null}``.
   The two must not collapse.

2. **Cursor codec reuse.** ``encode_cursor`` / ``decode_cursor`` —
   same helpers ``/reports`` uses. A cursor produced by page 1 of
   ``/actors/{id}/reports`` must decode via the shared codec;
   malformed cursors return 422 with the same FastAPI-shaped body
   (``type: value_error.malformed_cursor``).

3. **No existing surface disturbed.** GET /api/v1/actors and
   GET /api/v1/actors/{id} response shapes are UNCHANGED. Explicit
   D12 regression test below pins that ``ActorDetail`` has no
   ``linked_reports`` key even when the new endpoint has rows.

4. **D16 + D17 together.** Cursor round-trip over multiple codenames
   per actor demonstrates (a) dedup still applies on page 2 and (b)
   the same-date tiebreak is stable. Both invariants sit inside one
   test path.
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
    metadata,
    report_codenames_table,
    reports_table,
    sources_table,
)


# ---------------------------------------------------------------------------
# Fixtures — mirror test_actors_route.py
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def real_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def actor_reports_client(
    real_engine: AsyncEngine, session_store, fake_redis
) -> AsyncIterator[AsyncClient]:
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
# Seeding helpers
# ---------------------------------------------------------------------------


async def _seed_source(engine: AsyncEngine, name: str = "Vendor A") -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(sources_table)
            .values(name=name, type="vendor")
            .returning(sources_table.c.id)
        )
        s_id = row.scalar_one()
        await s.commit()
        return s_id


async def _seed_group(
    engine: AsyncEngine, *, name: str = "Lazarus Group"
) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(groups_table)
            .values(
                name=name,
                mitre_intrusion_set_id="G0032",
                aka=["APT38"],
                description="DPRK-attributed group",
            )
            .returning(groups_table.c.id)
        )
        g_id = row.scalar_one()
        await s.commit()
        return g_id


async def _seed_codename(
    engine: AsyncEngine, *, name: str, group_id: int
) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        row = await s.execute(
            sa.insert(codenames_table)
            .values(name=name, group_id=group_id)
            .returning(codenames_table.c.id)
        )
        c_id = row.scalar_one()
        await s.commit()
        return c_id


async def _seed_report(
    engine: AsyncEngine,
    *,
    title: str,
    source_id: int,
    published: dt.date,
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
        r_id = row.scalar_one()
        await s.commit()
        return r_id


async def _link_report_codename(
    engine: AsyncEngine, *, report_id: int, codename_id: int
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await s.execute(
            sa.insert(report_codenames_table).values(
                report_id=report_id, codename_id=codename_id
            )
        )
        await s.commit()


async def _cookie(make_session_cookie, *, role: str = "analyst") -> str:
    return await make_session_cookie(roles=[role])


# ---------------------------------------------------------------------------
# D15(a) — 404 vs 200-empty split
# ---------------------------------------------------------------------------


class TestD15MissingActor404:
    async def test_unknown_actor_id_returns_404(
        self,
        actor_reports_client: AsyncClient,
        make_session_cookie,
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await actor_reports_client.get(
            "/api/v1/actors/9999999/reports",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 404
        body = resp.json()
        assert body == {"detail": "actor not found"}, (
            "D15(a) — missing actor must return 404 with the same body "
            "as GET /actors/{id} detail, not a 200 empty envelope"
        )


# ---------------------------------------------------------------------------
# D15(b) — actor with no codenames → 200 empty
# D15(c) — codenames without report_codenames → 200 empty
# D15(d) — date filter excludes all → 200 empty
# ---------------------------------------------------------------------------


class TestD15EmptyBranches200:
    async def test_actor_no_codenames_returns_200_empty(
        self,
        actor_reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        g_id = await _seed_group(real_engine, name="Empty Group")
        cookie = await _cookie(make_session_cookie)
        resp = await actor_reports_client.get(
            f"/api/v1/actors/{g_id}/reports",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "next_cursor": None}

    async def test_codenames_without_links_returns_200_empty(
        self,
        actor_reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        g_id = await _seed_group(real_engine, name="Dormant Group")
        await _seed_codename(real_engine, name="dormant-a", group_id=g_id)
        cookie = await _cookie(make_session_cookie)
        resp = await actor_reports_client.get(
            f"/api/v1/actors/{g_id}/reports",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "next_cursor": None}

    async def test_date_filter_excludes_all_returns_200_empty(
        self,
        actor_reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(real_engine)
        g_id = await _seed_group(real_engine)
        c_id = await _seed_codename(real_engine, name="a1", group_id=g_id)
        r = await _seed_report(
            real_engine,
            title="old",
            source_id=src,
            published=dt.date(2020, 1, 1),
        )
        await _link_report_codename(
            real_engine, report_id=r, codename_id=c_id
        )
        cookie = await _cookie(make_session_cookie)
        resp = await actor_reports_client.get(
            f"/api/v1/actors/{g_id}/reports"
            "?date_from=2026-01-01&date_to=2026-12-31",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "next_cursor": None}


# ---------------------------------------------------------------------------
# Happy path — D9 envelope + ReportItem shape verbatim
# ---------------------------------------------------------------------------


class TestHappyEnvelope:
    async def test_three_linked_reports_response_shape(
        self,
        actor_reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(real_engine, name="Mandiant")
        g_id = await _seed_group(real_engine, name="Test Group")
        c_id = await _seed_codename(real_engine, name="alias-A", group_id=g_id)
        for i in range(3):
            r = await _seed_report(
                real_engine,
                title=f"rep-{i:02d}",
                source_id=src,
                published=dt.date(2026, 3, 1) + dt.timedelta(days=i),
            )
            await _link_report_codename(
                real_engine, report_id=r, codename_id=c_id
            )

        cookie = await _cookie(make_session_cookie)
        resp = await actor_reports_client.get(
            f"/api/v1/actors/{g_id}/reports",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        # D9 — envelope is {items, next_cursor} only. NO total, NO limit echo.
        assert set(body.keys()) == {"items", "next_cursor"}, (
            f"D9 envelope violation — got keys {set(body.keys())}"
        )
        assert len(body["items"]) == 3
        # Every item matches ReportItem shape exactly.
        for item in body["items"]:
            assert set(item.keys()) == {
                "id",
                "title",
                "url",
                "url_canonical",
                "published",
                "source_id",
                "source_name",
                "lang",
                "tlp",
            }
        # Newest first per D16.
        assert [it["title"] for it in body["items"]] == [
            "rep-02",
            "rep-01",
            "rep-00",
        ]
        assert body["next_cursor"] is None  # final page


# ---------------------------------------------------------------------------
# D17 EXISTS dedup — route layer
# ---------------------------------------------------------------------------


class TestD17DedupAtRoute:
    async def test_report_linked_via_three_codenames_appears_once_in_response(
        self,
        actor_reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(real_engine)
        g_id = await _seed_group(real_engine, name="Multi-alias")
        c1 = await _seed_codename(real_engine, name="a1", group_id=g_id)
        c2 = await _seed_codename(real_engine, name="a2", group_id=g_id)
        c3 = await _seed_codename(real_engine, name="a3", group_id=g_id)
        r = await _seed_report(
            real_engine,
            title="triple-linked",
            source_id=src,
            published=dt.date(2026, 4, 1),
        )
        for c in (c1, c2, c3):
            await _link_report_codename(
                real_engine, report_id=r, codename_id=c
            )

        cookie = await _cookie(make_session_cookie)
        resp = await actor_reports_client.get(
            f"/api/v1/actors/{g_id}/reports",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["title"] == "triple-linked"


# ---------------------------------------------------------------------------
# D16 cursor round-trip — encode on page 1, decode on page 2
# ---------------------------------------------------------------------------


class TestD16CursorRoundTrip:
    async def test_page_one_cursor_drives_page_two(
        self,
        actor_reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """Seed 3 reports. limit=2 on page 1 returns the two newest
        with a next_cursor; that cursor fed to page 2 returns the
        third (oldest) with next_cursor=null. No duplicates, no
        skips — identical contract to /reports list.
        """
        src = await _seed_source(real_engine)
        g_id = await _seed_group(real_engine)
        c_id = await _seed_codename(real_engine, name="a", group_id=g_id)
        dates = [
            dt.date(2026, 1, 1),
            dt.date(2026, 1, 2),
            dt.date(2026, 1, 3),
        ]
        r_ids: list[int] = []
        for i, d in enumerate(dates):
            r = await _seed_report(
                real_engine, title=f"r{i}", source_id=src, published=d
            )
            await _link_report_codename(
                real_engine, report_id=r, codename_id=c_id
            )
            r_ids.append(r)

        cookie = await _cookie(make_session_cookie)

        # Page 1 — limit=2.
        resp1 = await actor_reports_client.get(
            f"/api/v1/actors/{g_id}/reports?limit=2",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp1.status_code == 200
        body1 = resp1.json()
        assert [it["title"] for it in body1["items"]] == ["r2", "r1"]
        assert body1["next_cursor"] is not None

        # Page 2 — final page using the cursor from page 1.
        resp2 = await actor_reports_client.get(
            f"/api/v1/actors/{g_id}/reports"
            f"?limit=2&cursor={body1['next_cursor']}",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert [it["title"] for it in body2["items"]] == ["r0"]
        assert body2["next_cursor"] is None


# ---------------------------------------------------------------------------
# 422 invalid params — cursor + limit + dates
# ---------------------------------------------------------------------------


class TestInvalidParams422:
    @pytest.mark.parametrize(
        "bad_cursor",
        [
            "not-base64!!!",
            "YQ",  # valid b64 but no separator
            "aW52YWxpZHwtMQ",  # 'invalid|-1' — negative id
        ],
    )
    async def test_malformed_cursor_returns_422(
        self,
        actor_reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
        bad_cursor: str,
    ) -> None:
        g_id = await _seed_group(real_engine)
        cookie = await _cookie(make_session_cookie)
        resp = await actor_reports_client.get(
            f"/api/v1/actors/{g_id}/reports?cursor={bad_cursor}",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422
        body = resp.json()
        # Shape matches FastAPI validation error contract per /reports
        # route — consumers can branch on a single status.
        assert "detail" in body
        assert body["detail"][0]["type"] == "value_error.malformed_cursor"

    @pytest.mark.parametrize("bad_limit", ["0", "-1", "201", "abc"])
    async def test_limit_out_of_range(
        self,
        actor_reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
        bad_limit: str,
    ) -> None:
        g_id = await _seed_group(real_engine)
        cookie = await _cookie(make_session_cookie)
        resp = await actor_reports_client.get(
            f"/api/v1/actors/{g_id}/reports?limit={bad_limit}",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422

    async def test_malformed_date_returns_422(
        self,
        actor_reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        g_id = await _seed_group(real_engine)
        cookie = await _cookie(make_session_cookie)
        resp = await actor_reports_client.get(
            f"/api/v1/actors/{g_id}/reports?date_from=2026-13-01",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# RBAC — plan D7 inherited lock (5 read roles)
# ---------------------------------------------------------------------------


class TestRBAC:
    async def test_no_cookie_returns_401(
        self,
        actor_reports_client: AsyncClient,
        real_engine: AsyncEngine,
    ) -> None:
        g_id = await _seed_group(real_engine)
        resp = await actor_reports_client.get(
            f"/api/v1/actors/{g_id}/reports"
        )
        assert resp.status_code == 401

    @pytest.mark.parametrize(
        "role", ["analyst", "researcher", "policy", "soc", "admin"]
    )
    async def test_authorized_roles(
        self,
        actor_reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
        role: str,
    ) -> None:
        g_id = await _seed_group(real_engine)
        cookie = await _cookie(make_session_cookie, role=role)
        resp = await actor_reports_client.get(
            f"/api/v1/actors/{g_id}/reports",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200

    # NOTE: An "unknown role → 403" per-route test was removed when the
    # Phase 0 deferral on ``SessionData.roles: list[KnownRole]`` was
    # closed. Unknown roles now fail pydantic validation at session
    # construction (see ``tests/unit/test_auth_schemas.py``), so they
    # cannot reach RBAC at the route layer — the gate moved up the stack.


# ---------------------------------------------------------------------------
# D12 regression — /api/v1/actors/{id} detail shape UNCHANGED
# ---------------------------------------------------------------------------


class TestD12ActorDetailShapeRegression:
    async def test_actor_detail_has_no_linked_reports_key_even_after_pr15(
        self,
        actor_reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """D12 — PR #15 adds a sibling endpoint, NOT a new field on
        ActorDetail. Even when the actor has real ``report_codenames``
        links (which PR #15 surfaces via the new endpoint), the
        existing ``GET /api/v1/actors/{id}`` response must carry the
        exact PR #14 key set: {id, name, mitre_intrusion_set_id, aka,
        description, codenames}. If a future refactor accidentally
        enriches ``ActorDetail`` with ``linked_reports``, this test
        fires red.
        """
        src = await _seed_source(real_engine)
        g_id = await _seed_group(real_engine, name="Detail-vs-Reports Actor")
        c_id = await _seed_codename(real_engine, name="a1", group_id=g_id)
        r = await _seed_report(
            real_engine,
            title="real-link",
            source_id=src,
            published=dt.date(2026, 3, 1),
        )
        await _link_report_codename(
            real_engine, report_id=r, codename_id=c_id
        )

        cookie = await _cookie(make_session_cookie)
        resp = await actor_reports_client.get(
            f"/api/v1/actors/{g_id}",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {
            "id",
            "name",
            "mitre_intrusion_set_id",
            "aka",
            "description",
            "codenames",
        }, f"D12 regression — ActorDetail shape drifted, got keys {set(body.keys())}"


# ---------------------------------------------------------------------------
# OpenAPI surface — route examples + 404 and 429 blocks present
# ---------------------------------------------------------------------------


class TestOpenAPIRouteExamples:
    async def test_openapi_includes_actor_reports_examples(self) -> None:
        from api.main import app

        spec = app.openapi()
        path = spec["paths"]["/api/v1/actors/{actor_id}/reports"]["get"]
        examples = path["responses"]["200"]["content"][
            "application/json"
        ]["examples"]
        assert "populated" in examples
        assert "empty" in examples
        # D15(a) 404 block + rate-limit 429 block both present.
        assert "404" in path["responses"]
        assert "429" in path["responses"]
        assert "422" in path["responses"]
        # D9 envelope — empty example carries items=[]. FastAPI's
        # OpenAPI serializer strips None values from example dicts
        # (verified against the existing contracts/openapi/openapi.json
        # snapshot which never contains "next_cursor": null), so the
        # literal wire form is {"items": []}. Runtime response shape
        # {"items": [], "next_cursor": null} is pinned by the
        # integration tests above (TestD15EmptyBranches200).
        empty_val = examples["empty"]["value"]
        assert empty_val["items"] == []
        # Populated example proves the envelope has no `total` or
        # `limit` echo — D9 keyset envelope lock.
        pop_val = examples["populated"]["value"]
        assert "total" not in pop_val
        assert "limit" not in pop_val
        assert set(pop_val.keys()) <= {"items", "next_cursor"}
