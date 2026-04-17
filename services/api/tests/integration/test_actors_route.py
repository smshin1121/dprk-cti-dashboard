"""Integration tests for GET /api/v1/actors (PR #11 Group B).

Runs against in-memory aiosqlite via dependency override, matching
the pattern in ``test_staging_routes.py``. Real-PG scenarios land in
``tests/integration/test_read_real_pg.py`` in Group K.

Review checklist (plan §2.1 D3 / D11 / D12 / D13):

1. Default sort ``name ASC, id ASC`` (D11) verified by seeding
   out-of-order rows and asserting response order.
2. Offset pagination limits / offsets out of range return 422 from
   FastAPI Query bounds — no silent ignore (D12).
3. Codenames flatten per group; groups with no codenames return
   an empty list, not null.
4. RBAC triad expanded (analyst / researcher / policy / soc / admin).
   403 for any other role.
5. Shape matches ``ActorListResponse`` exactly — ``next_cursor``
   does not appear (actors uses offset, D3).
"""

from __future__ import annotations

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

from api.tables import codenames_table, groups_table, metadata


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def real_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def actors_client(
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


async def _seed_groups(
    engine: AsyncEngine, groups: list[dict]
) -> list[int]:
    ids: list[int] = []
    async with AsyncSession(engine, expire_on_commit=False) as s:
        for g in groups:
            result = await s.execute(
                sa.insert(groups_table).values(**g).returning(groups_table.c.id)
            )
            ids.append(result.scalar_one())
        await s.commit()
    return ids


async def _seed_codenames(
    engine: AsyncEngine, codenames: list[dict]
) -> list[int]:
    ids: list[int] = []
    async with AsyncSession(engine, expire_on_commit=False) as s:
        for c in codenames:
            result = await s.execute(
                sa.insert(codenames_table).values(**c).returning(codenames_table.c.id)
            )
            ids.append(result.scalar_one())
        await s.commit()
    return ids


async def _cookie(make_session_cookie, *, role: str = "analyst") -> str:
    return await make_session_cookie(roles=[role])


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestListActorsHappy:
    async def test_empty_db_returns_empty_page(
        self, actors_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await actors_client.get(
            "/api/v1/actors", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"items": [], "limit": 50, "offset": 0, "total": 0}
        assert "next_cursor" not in body  # D3 — offset envelope, not keyset

    async def test_three_groups_sorted_by_name(
        self,
        actors_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """Seed in non-alphabetical order. Response must be alphabetical
        per plan D11 default sort name ASC, id ASC."""
        await _seed_groups(
            real_engine,
            [
                {"name": "Lazarus Group", "mitre_intrusion_set_id": "G0032", "aka": ["APT38"]},
                {"name": "Andariel", "mitre_intrusion_set_id": "G0138", "aka": []},
                {"name": "Kimsuky", "mitre_intrusion_set_id": "G0094", "aka": ["Velvet Chollima"]},
            ],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await actors_client.get(
            "/api/v1/actors", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 200
        body = resp.json()
        names = [item["name"] for item in body["items"]]
        assert names == ["Andariel", "Kimsuky", "Lazarus Group"]
        assert body["total"] == 3

    async def test_codenames_flatten_per_group(
        self,
        actors_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        group_ids = await _seed_groups(
            real_engine,
            [
                {"name": "Lazarus Group", "mitre_intrusion_set_id": "G0032"},
                {"name": "Kimsuky", "mitre_intrusion_set_id": "G0094"},
            ],
        )
        await _seed_codenames(
            real_engine,
            [
                {"name": "Andariel", "group_id": group_ids[0]},
                {"name": "Bluenoroff", "group_id": group_ids[0]},
                {"name": "Velvet Chollima", "group_id": group_ids[1]},
            ],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await actors_client.get(
            "/api/v1/actors", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 200
        items = {item["name"]: item for item in resp.json()["items"]}
        assert sorted(items["Lazarus Group"]["codenames"]) == ["Andariel", "Bluenoroff"]
        assert items["Kimsuky"]["codenames"] == ["Velvet Chollima"]

    async def test_group_with_no_codenames_returns_empty_list(
        self,
        actors_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        await _seed_groups(
            real_engine, [{"name": "Solo Group", "mitre_intrusion_set_id": None}]
        )
        cookie = await _cookie(make_session_cookie)
        resp = await actors_client.get(
            "/api/v1/actors", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert item["codenames"] == []

    async def test_aka_surfaces_as_list(
        self,
        actors_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        await _seed_groups(
            real_engine,
            [{"name": "Lazarus Group", "aka": ["APT38", "Hidden Cobra"]}],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await actors_client.get(
            "/api/v1/actors", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 200
        assert resp.json()["items"][0]["aka"] == ["APT38", "Hidden Cobra"]


# ---------------------------------------------------------------------------
# Offset pagination
# ---------------------------------------------------------------------------


class TestOffsetPagination:
    async def test_limit_shrinks_page(
        self,
        actors_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        await _seed_groups(
            real_engine,
            [{"name": f"Group{i:02d}"} for i in range(5)],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await actors_client.get(
            "/api/v1/actors?limit=2",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 2
        assert body["limit"] == 2
        assert body["offset"] == 0
        assert body["total"] == 5  # total reflects the full set

    async def test_offset_skips_forward(
        self,
        actors_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        await _seed_groups(
            real_engine,
            [{"name": f"Group{i:02d}"} for i in range(5)],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await actors_client.get(
            "/api/v1/actors?limit=2&offset=2",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        names = [it["name"] for it in body["items"]]
        assert names == ["Group02", "Group03"]
        assert body["offset"] == 2


# ---------------------------------------------------------------------------
# Invalid params — plan D12 uniform 422
# ---------------------------------------------------------------------------


class TestInvalidParams422:
    @pytest.mark.parametrize("bad_limit", ["0", "-1", "201", "abc"])
    async def test_limit_out_of_range(
        self,
        actors_client: AsyncClient,
        make_session_cookie,
        bad_limit: str,
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await actors_client.get(
            f"/api/v1/actors?limit={bad_limit}",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("bad_offset", ["-1", "abc"])
    async def test_offset_invalid(
        self,
        actors_client: AsyncClient,
        make_session_cookie,
        bad_offset: str,
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await actors_client.get(
            f"/api/v1/actors?offset={bad_offset}",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# RBAC — plan §9.3 / inherited lock
# ---------------------------------------------------------------------------


class TestRBAC:
    async def test_no_cookie_returns_401(self, actors_client: AsyncClient) -> None:
        resp = await actors_client.get("/api/v1/actors")
        assert resp.status_code == 401

    @pytest.mark.parametrize(
        "role", ["analyst", "researcher", "policy", "soc", "admin"]
    )
    async def test_authorized_roles(
        self,
        actors_client: AsyncClient,
        make_session_cookie,
        role: str,
    ) -> None:
        cookie = await _cookie(make_session_cookie, role=role)
        resp = await actors_client.get(
            "/api/v1/actors", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 200

    async def test_unknown_role_403(
        self, actors_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie, role="unknown_role")
        resp = await actors_client.get(
            "/api/v1/actors", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# OpenAPI surface — plan D13 router examples
# ---------------------------------------------------------------------------


class TestOpenAPIRouterExamples:
    async def test_openapi_includes_actors_examples(self) -> None:
        """Plan D13: router-level examples (happy / empty) must land
        in the OpenAPI schema so Swagger and Redoc render them.

        The live ``/openapi.json`` route is gated to ``APP_ENV=dev``
        (main.py `_openapi_url`), so we call the FastAPI introspection
        hook directly — same schema FastAPI serves in dev, but without
        the env gate.
        """
        from api.main import app

        spec = app.openapi()
        path = spec["paths"]["/api/v1/actors"]["get"]
        examples = path["responses"]["200"]["content"]["application/json"]["examples"]
        assert "happy" in examples
        assert "empty" in examples
        assert examples["happy"]["value"]["total"] == 3
        assert examples["empty"]["value"]["items"] == []
