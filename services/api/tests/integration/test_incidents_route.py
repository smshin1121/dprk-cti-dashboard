"""Integration tests for GET /api/v1/incidents (PR #11 Group D).

Runs on in-memory aiosqlite via dependency override. Real-PG
scenario 3 in ``test_read_real_pg.py`` covers PG-specific
array_agg behavior and the multi-country OR planner path.

Review checklist from the Group D lock:

1. One incident with N motivations + M sectors + K countries must
   appear as EXACTLY ONE item. Correlated scalar subqueries keep
   the outer row count invariant where LEFT JOIN + GROUP BY would
   multiply rows by N*M*K.
2. ``reported DESC, id DESC`` is pinned in SQL and tested.
3. Aggregated arrays (motivations / sectors / countries) are
   returned in stable sorted order so repeated calls yield
   identical payloads.
4. Every invalid filter surfaces as HTTP 422 — empty repeatable
   items, non-alpha-2 country, bad ISO date, malformed cursor,
   out-of-range limit.
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
    incident_countries_table,
    incident_motivations_table,
    incident_sectors_table,
    incidents_table,
    metadata,
)


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
async def incidents_client(
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
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_incident(
    engine: AsyncEngine,
    *,
    title: str,
    reported: dt.date | None,
    motivations: list[str] | None = None,
    sectors: list[str] | None = None,
    countries: list[str] | None = None,
    description: str | None = None,
    est_loss_usd: int | None = None,
) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        result = await s.execute(
            sa.insert(incidents_table)
            .values(
                title=title,
                reported=reported,
                description=description,
                est_loss_usd=est_loss_usd,
            )
            .returning(incidents_table.c.id)
        )
        iid = result.scalar_one()

        for m in motivations or []:
            await s.execute(
                sa.insert(incident_motivations_table).values(
                    incident_id=iid, motivation=m
                )
            )
        for sec in sectors or []:
            await s.execute(
                sa.insert(incident_sectors_table).values(
                    incident_id=iid, sector_code=sec
                )
            )
        for c in countries or []:
            await s.execute(
                sa.insert(incident_countries_table).values(
                    incident_id=iid, country_iso2=c
                )
            )
        await s.commit()
        return iid


async def _cookie(make_session_cookie, *, role: str = "analyst") -> str:
    return await make_session_cookie(roles=[role])


# ---------------------------------------------------------------------------
# Review priority #1 — ONE item per incident despite multi-join
# ---------------------------------------------------------------------------


class TestMultiJoinDedup:
    async def test_incident_with_n_motivations_m_sectors_k_countries_returns_once(
        self,
        incidents_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """Seed one incident with 2 motivations × 3 sectors × 2 countries.
        A naive LEFT JOIN would multiply to 12 rows — the response must
        still carry exactly ONE item."""
        iid = await _seed_incident(
            real_engine,
            title="Multi-join incident",
            reported=dt.date(2024, 5, 2),
            motivations=["financial", "espionage"],
            sectors=["crypto", "finance", "gov"],
            countries=["KR", "US"],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await incidents_client.get(
            "/api/v1/incidents", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        ids = [it["id"] for it in items]
        assert ids == [iid]
        assert len(items) == 1
        item = items[0]
        # All aggregated arrays round-trip with expected cardinality.
        assert set(item["motivations"]) == {"financial", "espionage"}
        assert set(item["sectors"]) == {"crypto", "finance", "gov"}
        assert set(item["countries"]) == {"KR", "US"}


# ---------------------------------------------------------------------------
# Review priority #2 — reported DESC, id DESC default sort
# ---------------------------------------------------------------------------


class TestDefaultSort:
    async def test_sort_reported_desc(
        self,
        incidents_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        for d in [dt.date(2022, 1, 1), dt.date(2024, 5, 2), dt.date(2023, 6, 10)]:
            await _seed_incident(
                real_engine, title=f"i-{d}", reported=d
            )
        cookie = await _cookie(make_session_cookie)
        resp = await incidents_client.get(
            "/api/v1/incidents", cookies={"dprk_cti_session": cookie}
        )
        reported = [it["reported"] for it in resp.json()["items"]]
        assert reported == ["2024-05-02", "2023-06-10", "2022-01-01"]

    async def test_tiebreak_same_day_uses_id_desc(
        self,
        incidents_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        ids = []
        for i in range(3):
            iid = await _seed_incident(
                real_engine,
                title=f"same-day-{i}",
                reported=dt.date(2024, 5, 2),
            )
            ids.append(iid)
        cookie = await _cookie(make_session_cookie)
        resp = await incidents_client.get(
            "/api/v1/incidents", cookies={"dprk_cti_session": cookie}
        )
        response_ids = [it["id"] for it in resp.json()["items"]]
        assert response_ids == sorted(ids, reverse=True)

    async def test_null_reported_excluded(
        self,
        incidents_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """Documented limitation — null-reported incidents drop from
        the list. Phase 3 detail endpoints can surface them."""
        await _seed_incident(real_engine, title="has date", reported=dt.date(2024, 1, 1))
        await _seed_incident(real_engine, title="no date", reported=None)
        cookie = await _cookie(make_session_cookie)
        resp = await incidents_client.get(
            "/api/v1/incidents", cookies={"dprk_cti_session": cookie}
        )
        titles = [it["title"] for it in resp.json()["items"]]
        assert titles == ["has date"]


# ---------------------------------------------------------------------------
# Review priority #3 — aggregated arrays stable order
# ---------------------------------------------------------------------------


class TestAggregateStableOrder:
    async def test_arrays_sorted_ascending(
        self,
        incidents_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """Seed in non-alphabetical order; expect alphabetical in response."""
        await _seed_incident(
            real_engine,
            title="stable sort",
            reported=dt.date(2024, 5, 2),
            motivations=["financial", "disruption", "espionage"],
            sectors=["gov", "crypto", "finance"],
            countries=["US", "KR", "JP"],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await incidents_client.get(
            "/api/v1/incidents", cookies={"dprk_cti_session": cookie}
        )
        item = resp.json()["items"][0]
        assert item["motivations"] == sorted(item["motivations"])
        assert item["sectors"] == sorted(item["sectors"])
        assert item["countries"] == sorted(item["countries"])

    async def test_empty_arrays_default_empty_list(
        self,
        incidents_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        await _seed_incident(real_engine, title="bare", reported=dt.date(2024, 1, 1))
        cookie = await _cookie(make_session_cookie)
        resp = await incidents_client.get(
            "/api/v1/incidents", cookies={"dprk_cti_session": cookie}
        )
        item = resp.json()["items"][0]
        assert item["motivations"] == []
        assert item["sectors"] == []
        assert item["countries"] == []


# ---------------------------------------------------------------------------
# Filter AND/OR contract (plan D5)
# ---------------------------------------------------------------------------


class TestFilterSemantics:
    async def _setup_matrix(self, engine: AsyncEngine) -> dict[str, int]:
        """Seed 4 incidents with varied motivation/country combos."""
        return {
            "fin_kr": await _seed_incident(
                engine,
                title="fin-kr",
                reported=dt.date(2024, 1, 1),
                motivations=["financial"],
                countries=["KR"],
            ),
            "esp_us": await _seed_incident(
                engine,
                title="esp-us",
                reported=dt.date(2024, 2, 1),
                motivations=["espionage"],
                countries=["US"],
            ),
            "fin_us": await _seed_incident(
                engine,
                title="fin-us",
                reported=dt.date(2024, 3, 1),
                motivations=["financial"],
                countries=["US"],
            ),
            "dis_jp": await _seed_incident(
                engine,
                title="dis-jp",
                reported=dt.date(2024, 4, 1),
                motivations=["disruption"],
                countries=["JP"],
            ),
        }

    async def test_motivation_repeat_or(
        self,
        incidents_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        ids = await self._setup_matrix(real_engine)
        cookie = await _cookie(make_session_cookie)
        resp = await incidents_client.get(
            "/api/v1/incidents?motivation=financial&motivation=espionage",
            cookies={"dprk_cti_session": cookie},
        )
        got = {it["id"] for it in resp.json()["items"]}
        assert got == {ids["fin_kr"], ids["esp_us"], ids["fin_us"]}

    async def test_country_repeat_or(
        self,
        incidents_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        ids = await self._setup_matrix(real_engine)
        cookie = await _cookie(make_session_cookie)
        resp = await incidents_client.get(
            "/api/v1/incidents?country=KR&country=US",
            cookies={"dprk_cti_session": cookie},
        )
        got = {it["id"] for it in resp.json()["items"]}
        assert got == {ids["fin_kr"], ids["esp_us"], ids["fin_us"]}

    async def test_motivation_and_country_and(
        self,
        incidents_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """motivation=financial & country=US → only fin_us."""
        ids = await self._setup_matrix(real_engine)
        cookie = await _cookie(make_session_cookie)
        resp = await incidents_client.get(
            "/api/v1/incidents?motivation=financial&country=US",
            cookies={"dprk_cti_session": cookie},
        )
        got = {it["id"] for it in resp.json()["items"]}
        assert got == {ids["fin_us"]}

    async def test_country_lowercase_normalized(
        self,
        incidents_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        await _seed_incident(
            real_engine,
            title="kr",
            reported=dt.date(2024, 1, 1),
            countries=["KR"],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await incidents_client.get(
            "/api/v1/incidents?country=kr",  # lowercase query
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1


# ---------------------------------------------------------------------------
# Cursor
# ---------------------------------------------------------------------------


class TestCursor:
    async def test_cursor_page1_to_page2(
        self,
        incidents_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        for m in range(1, 6):  # 5 incidents across 2024-01..2024-05
            await _seed_incident(
                real_engine, title=f"i-{m}", reported=dt.date(2024, m, 1)
            )
        cookie = await _cookie(make_session_cookie)
        resp1 = await incidents_client.get(
            "/api/v1/incidents?limit=2", cookies={"dprk_cti_session": cookie}
        )
        body1 = resp1.json()
        assert len(body1["items"]) == 2
        assert body1["next_cursor"] is not None

        resp2 = await incidents_client.get(
            f"/api/v1/incidents?limit=2&cursor={body1['next_cursor']}",
            cookies={"dprk_cti_session": cookie},
        )
        page1_ids = {it["id"] for it in body1["items"]}
        page2_ids = {it["id"] for it in resp2.json()["items"]}
        assert page1_ids.isdisjoint(page2_ids)


# ---------------------------------------------------------------------------
# Review priority #4 — invalid → 422
# ---------------------------------------------------------------------------


class TestInvalid422:
    @pytest.mark.parametrize(
        "bad_qs",
        [
            "?motivation=",  # empty repeat
            "?sector=",
            "?country=",
            "?country=korea",  # non-alpha-2
            "?country=K",  # one letter
            "?country=KR1",  # 3 chars
            "?date_from=not-a-date",
            "?date_to=2024-13-01",
            "?limit=0",
            "?limit=201",
        ],
    )
    async def test_invalid_query_422(
        self,
        incidents_client: AsyncClient,
        make_session_cookie,
        bad_qs: str,
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await incidents_client.get(
            f"/api/v1/incidents{bad_qs}",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422, f"{bad_qs} expected 422, got {resp.status_code}"

    async def test_malformed_cursor_422(
        self, incidents_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await incidents_client.get(
            "/api/v1/incidents?cursor=garbled!",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"][0]["loc"] == ["query", "cursor"]


# ---------------------------------------------------------------------------
# RBAC + OpenAPI examples
# ---------------------------------------------------------------------------


class TestRBAC:
    async def test_no_cookie_401(self, incidents_client: AsyncClient) -> None:
        resp = await incidents_client.get("/api/v1/incidents")
        assert resp.status_code == 401

    @pytest.mark.parametrize(
        "role", ["analyst", "researcher", "policy", "soc", "admin"]
    )
    async def test_authorized_roles(
        self,
        incidents_client: AsyncClient,
        make_session_cookie,
        role: str,
    ) -> None:
        cookie = await _cookie(make_session_cookie, role=role)
        resp = await incidents_client.get(
            "/api/v1/incidents", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 200

    # NOTE: An "unknown role → 403" per-route test was removed when the
    # Phase 0 deferral on ``SessionData.roles: list[KnownRole]`` was
    # closed. Unknown roles now fail pydantic validation at session
    # construction (see ``tests/unit/test_auth_schemas.py``).


class TestOpenAPIRouterExamples:
    async def test_openapi_includes_incidents_examples(self) -> None:
        from api.main import app

        spec = app.openapi()
        path = spec["paths"]["/api/v1/incidents"]["get"]
        examples = path["responses"]["200"]["content"]["application/json"]["examples"]
        assert "happy" in examples
        assert "last_page" in examples
