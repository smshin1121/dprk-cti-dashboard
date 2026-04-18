"""Integration tests for GET /api/v1/reports (PR #11 Group C).

Runs against in-memory aiosqlite via dependency override. Real-PG
scenarios (ILIKE case semantics, array_agg, large page counts) land
in ``tests/integration/test_read_real_pg.py``.

Review checklist from the Group C lock:

1. ``published DESC, id DESC`` keyset — SQL ORDER BY and cursor
   condition must stay in lock-step. Tests verify default page sort,
   cursor round-trip stability, and the tie-breaker for same-day
   reports.
2. Every filter param collapses to HTTP 422 on invalid input
   (plan D12). Empty ``q``, empty ``tag`` / ``source``, bad ISO
   date, malformed cursor, out-of-range ``limit`` — all 422.
3. No row duplication under tag JOIN. A report with two matching
   tags must still surface as exactly ONE item.
4. Repeatable filter AND/OR contract (plan D5):
     - ``?tag=a&tag=b`` = OR inside tag (matches either tag)
     - ``?tag=a&source=X`` = AND across params (matches BOTH)
   Tests pin both edges.
"""

from __future__ import annotations

import base64
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
    metadata,
    report_tags_table,
    reports_table,
    sources_table,
    tags_table,
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
async def reports_client(
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


async def _seed_source(engine: AsyncEngine, name: str) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        result = await s.execute(
            sa.insert(sources_table)
            .values(name=name, type="vendor")
            .returning(sources_table.c.id)
        )
        src_id = result.scalar_one()
        await s.commit()
        return src_id


async def _seed_tag(engine: AsyncEngine, name: str, type_: str = "actor") -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        result = await s.execute(
            sa.insert(tags_table)
            .values(name=name, type=type_)
            .returning(tags_table.c.id)
        )
        tag_id = result.scalar_one()
        await s.commit()
        return tag_id


async def _seed_report(
    engine: AsyncEngine,
    *,
    title: str,
    url: str,
    source_id: int,
    published: dt.date,
    url_canonical: str | None = None,
    sha256_title: str | None = None,
    lang: str = "en",
) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        result = await s.execute(
            sa.insert(reports_table)
            .values(
                title=title,
                url=url,
                url_canonical=url_canonical or url,
                sha256_title=sha256_title or f"sha-{title[:16]}",
                source_id=source_id,
                published=published,
                lang=lang,
            )
            .returning(reports_table.c.id)
        )
        rid = result.scalar_one()
        await s.commit()
        return rid


async def _link_report_tag(
    engine: AsyncEngine, *, report_id: int, tag_id: int
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await s.execute(
            sa.insert(report_tags_table).values(report_id=report_id, tag_id=tag_id)
        )
        await s.commit()


async def _cookie(make_session_cookie, *, role: str = "analyst") -> str:
    return await make_session_cookie(roles=[role])


# ---------------------------------------------------------------------------
# Default sort + keyset cursor (review priority #1)
# ---------------------------------------------------------------------------


class TestDefaultSortAndCursor:
    async def test_sort_published_desc(
        self,
        reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(real_engine, "src-a")
        for i, d in enumerate([
            dt.date(2024, 1, 1),
            dt.date(2026, 3, 15),  # newest — should be first
            dt.date(2025, 6, 10),
        ]):
            await _seed_report(
                real_engine,
                title=f"t-{i}",
                url=f"https://ex/{i}",
                source_id=src,
                published=d,
            )
        cookie = await _cookie(make_session_cookie)
        resp = await reports_client.get(
            "/api/v1/reports", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 200
        published_dates = [item["published"] for item in resp.json()["items"]]
        assert published_dates == ["2026-03-15", "2025-06-10", "2024-01-01"]

    async def test_tiebreak_same_day_uses_id_desc(
        self,
        reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """Two reports on the same day must be ordered by id DESC
        (latest-inserted first) — plan D11 keyset tie-breaker."""
        src = await _seed_source(real_engine, "src-a")
        for i in range(3):
            await _seed_report(
                real_engine,
                title=f"same-day-{i}",
                url=f"https://ex/sd-{i}",
                source_id=src,
                published=dt.date(2026, 3, 15),
            )
        cookie = await _cookie(make_session_cookie)
        resp = await reports_client.get(
            "/api/v1/reports", cookies={"dprk_cti_session": cookie}
        )
        ids = [item["id"] for item in resp.json()["items"]]
        assert ids == sorted(ids, reverse=True)  # DESC

    async def test_cursor_round_trip_page1_to_page2(
        self,
        reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """Page 1 limit=2 returns newest 2 + next_cursor. Page 2
        cursor returns the rest, no overlap, no skip."""
        src = await _seed_source(real_engine, "src-a")
        days = [dt.date(2026, m, 1) for m in (1, 2, 3, 4, 5)]  # 5 reports
        for i, d in enumerate(days):
            await _seed_report(
                real_engine,
                title=f"r-{i}",
                url=f"https://ex/r{i}",
                source_id=src,
                published=d,
            )
        cookie = await _cookie(make_session_cookie)
        resp1 = await reports_client.get(
            "/api/v1/reports?limit=2", cookies={"dprk_cti_session": cookie}
        )
        assert resp1.status_code == 200
        body1 = resp1.json()
        assert len(body1["items"]) == 2
        assert body1["next_cursor"] is not None

        resp2 = await reports_client.get(
            f"/api/v1/reports?limit=2&cursor={body1['next_cursor']}",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp2.status_code == 200
        body2 = resp2.json()
        page1_ids = {it["id"] for it in body1["items"]}
        page2_ids = {it["id"] for it in body2["items"]}
        assert page1_ids.isdisjoint(page2_ids), "pages must not overlap"
        assert len(body1["items"]) + len(body2["items"]) <= 5

    async def test_cursor_null_on_last_page(
        self,
        reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(real_engine, "src-a")
        await _seed_report(
            real_engine,
            title="only",
            url="https://ex/only",
            source_id=src,
            published=dt.date(2026, 3, 15),
        )
        cookie = await _cookie(make_session_cookie)
        resp = await reports_client.get(
            "/api/v1/reports", cookies={"dprk_cti_session": cookie}
        )
        assert resp.json()["next_cursor"] is None


# ---------------------------------------------------------------------------
# Tag / source AND/OR contract (review priority #4)
# ---------------------------------------------------------------------------


class TestTagSourceFilterSemantics:
    async def _setup_three_reports_two_tags(
        self, real_engine: AsyncEngine
    ) -> tuple[dict[str, int], dict[str, int]]:
        """Seed: 3 reports, tags ransomware + espionage, sources A + B.

        - r_both: tags=[ransomware, espionage], source=A
        - r_rans: tags=[ransomware],           source=A
        - r_esp:  tags=[espionage],            source=B
        Returns (report_ids_by_label, tag_ids_by_name).
        """
        src_a = await _seed_source(real_engine, "src-A")
        src_b = await _seed_source(real_engine, "src-B")
        tag_rans = await _seed_tag(real_engine, "ransomware")
        tag_esp = await _seed_tag(real_engine, "espionage")

        r_both = await _seed_report(
            real_engine,
            title="both",
            url="https://ex/both",
            source_id=src_a,
            published=dt.date(2026, 3, 15),
        )
        r_rans = await _seed_report(
            real_engine,
            title="rans only",
            url="https://ex/rans",
            source_id=src_a,
            published=dt.date(2026, 3, 14),
        )
        r_esp = await _seed_report(
            real_engine,
            title="esp only",
            url="https://ex/esp",
            source_id=src_b,
            published=dt.date(2026, 3, 13),
        )

        for tid in (tag_rans, tag_esp):
            await _link_report_tag(real_engine, report_id=r_both, tag_id=tid)
        await _link_report_tag(real_engine, report_id=r_rans, tag_id=tag_rans)
        await _link_report_tag(real_engine, report_id=r_esp, tag_id=tag_esp)

        return (
            {"both": r_both, "rans": r_rans, "esp": r_esp},
            {"ransomware": tag_rans, "espionage": tag_esp},
        )

    async def test_tag_repeat_or_inside(
        self,
        reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """?tag=ransomware&tag=espionage returns all 3 reports
        (any that carry at least one)."""
        report_ids, _ = await self._setup_three_reports_two_tags(real_engine)
        cookie = await _cookie(make_session_cookie)
        resp = await reports_client.get(
            "/api/v1/reports?tag=ransomware&tag=espionage",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        ids = {it["id"] for it in resp.json()["items"]}
        assert ids == set(report_ids.values())

    async def test_tag_single_matches_both_carriers(
        self,
        reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """?tag=ransomware returns r_both + r_rans (both carry it);
        r_esp drops out."""
        report_ids, _ = await self._setup_three_reports_two_tags(real_engine)
        cookie = await _cookie(make_session_cookie)
        resp = await reports_client.get(
            "/api/v1/reports?tag=ransomware",
            cookies={"dprk_cti_session": cookie},
        )
        ids = {it["id"] for it in resp.json()["items"]}
        assert ids == {report_ids["both"], report_ids["rans"]}

    async def test_tag_and_source_and_across(
        self,
        reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """?tag=ransomware&source=src-A requires BOTH.

        r_both: matches (tag + source)
        r_rans: matches (tag + source)
        r_esp:  source mismatch → excluded
        """
        report_ids, _ = await self._setup_three_reports_two_tags(real_engine)
        cookie = await _cookie(make_session_cookie)
        resp = await reports_client.get(
            "/api/v1/reports?tag=ransomware&source=src-A",
            cookies={"dprk_cti_session": cookie},
        )
        ids = {it["id"] for it in resp.json()["items"]}
        assert ids == {report_ids["both"], report_ids["rans"]}

    async def test_source_repeat_or_inside(
        self,
        reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        report_ids, _ = await self._setup_three_reports_two_tags(real_engine)
        cookie = await _cookie(make_session_cookie)
        resp = await reports_client.get(
            "/api/v1/reports?source=src-A&source=src-B",
            cookies={"dprk_cti_session": cookie},
        )
        assert len(resp.json()["items"]) == 3


# ---------------------------------------------------------------------------
# JOIN row dedup (review priority #3)
# ---------------------------------------------------------------------------


class TestJOINDedup:
    async def test_report_with_two_matching_tags_appears_once(
        self,
        reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """A report tagged both ``ransomware`` and ``espionage`` must
        appear exactly once when BOTH tags are in the filter — EXISTS
        semantics means no row multiplication."""
        src = await _seed_source(real_engine, "src-a")
        tag_a = await _seed_tag(real_engine, "ransomware")
        tag_b = await _seed_tag(real_engine, "espionage")
        rid = await _seed_report(
            real_engine,
            title="dual tagged",
            url="https://ex/dual",
            source_id=src,
            published=dt.date(2026, 3, 15),
        )
        for tid in (tag_a, tag_b):
            await _link_report_tag(real_engine, report_id=rid, tag_id=tid)

        cookie = await _cookie(make_session_cookie)
        resp = await reports_client.get(
            "/api/v1/reports?tag=ransomware&tag=espionage",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        # Same id must not appear twice.
        ids = [it["id"] for it in items]
        assert ids == [rid]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# q + date range filters
# ---------------------------------------------------------------------------


class TestQAndDateRangeFilters:
    async def test_q_title_substring(
        self,
        reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(real_engine, "src-a")
        for title in ["Lazarus crypto", "Kimsuky phishing", "Andariel tools"]:
            await _seed_report(
                real_engine,
                title=title,
                url=f"https://ex/{title[:6].replace(' ', '-')}",
                source_id=src,
                published=dt.date(2026, 3, 15),
            )
        cookie = await _cookie(make_session_cookie)
        resp = await reports_client.get(
            "/api/v1/reports?q=crypto", cookies={"dprk_cti_session": cookie}
        )
        titles = [it["title"] for it in resp.json()["items"]]
        assert titles == ["Lazarus crypto"]

    async def test_date_from_to_inclusive(
        self,
        reports_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        src = await _seed_source(real_engine, "src-a")
        for i, d in enumerate([
            dt.date(2026, 1, 1),
            dt.date(2026, 3, 15),  # in range
            dt.date(2026, 6, 1),
        ]):
            await _seed_report(
                real_engine,
                title=f"t-{i}",
                url=f"https://ex/d{i}",
                source_id=src,
                published=d,
            )
        cookie = await _cookie(make_session_cookie)
        resp = await reports_client.get(
            "/api/v1/reports?date_from=2026-02-01&date_to=2026-04-30",
            cookies={"dprk_cti_session": cookie},
        )
        published = [it["published"] for it in resp.json()["items"]]
        assert published == ["2026-03-15"]


# ---------------------------------------------------------------------------
# Invalid inputs — plan D12 uniform 422 (review priority #2)
# ---------------------------------------------------------------------------


class TestInvalid422:
    @pytest.mark.parametrize(
        "bad_qs",
        [
            "?q=",  # empty q — min_length=1 violation
            "?tag=",  # empty tag repeat
            "?source=",  # empty source repeat
            "?date_from=not-a-date",
            "?date_to=2026-13-01",  # invalid month
            "?date_from=2026-02-31",  # invalid day
            "?limit=0",
            "?limit=201",
            "?limit=abc",
        ],
    )
    async def test_invalid_query_returns_422(
        self,
        reports_client: AsyncClient,
        make_session_cookie,
        bad_qs: str,
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await reports_client.get(
            f"/api/v1/reports{bad_qs}",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422, f"{bad_qs} should be 422, got {resp.status_code}"

    async def test_malformed_cursor_returns_422(
        self, reports_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        # Valid base64 of a payload missing the ``|`` separator
        bad = base64.urlsafe_b64encode(b"not-a-cursor").decode("ascii").rstrip("=")
        resp = await reports_client.get(
            f"/api/v1/reports?cursor={bad}",
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422
        body = resp.json()
        # Body mirrors FastAPI HTTPValidationError shape so FE handlers
        # branch on detail[].loc[] uniformly.
        assert isinstance(body.get("detail"), list)
        assert body["detail"][0]["loc"] == ["query", "cursor"]


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


class TestRBAC:
    async def test_no_cookie_401(self, reports_client: AsyncClient) -> None:
        resp = await reports_client.get("/api/v1/reports")
        assert resp.status_code == 401

    @pytest.mark.parametrize(
        "role", ["analyst", "researcher", "policy", "soc", "admin"]
    )
    async def test_authorized_roles(
        self,
        reports_client: AsyncClient,
        make_session_cookie,
        role: str,
    ) -> None:
        cookie = await _cookie(make_session_cookie, role=role)
        resp = await reports_client.get(
            "/api/v1/reports", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 200

    async def test_unknown_role_403(
        self, reports_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie, role="unknown_role")
        resp = await reports_client.get(
            "/api/v1/reports", cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# OpenAPI router-level examples (plan D13)
# ---------------------------------------------------------------------------


class TestOpenAPIRouterExamples:
    async def test_openapi_includes_reports_examples(self) -> None:
        from api.main import app

        spec = app.openapi()
        path = spec["paths"]["/api/v1/reports"]["get"]
        examples = path["responses"]["200"]["content"]["application/json"]["examples"]
        assert "happy" in examples
        assert "last_page" in examples
        assert examples["happy"]["value"]["items"][0]["id"] == 42
