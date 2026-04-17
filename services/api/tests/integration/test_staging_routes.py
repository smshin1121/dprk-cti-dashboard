"""Integration tests for GET /api/v1/staging/{review,{id}}.

Group E reviewer checklist:

1. ``ORDER BY created_at ASC, id ASC`` is pinned in both the SQL
   path and in tests — regressions on default ordering fail loudly.
2. Cursor pagination is keyset-style on ``(created_at, id)``; stable
   when rows are inserted after page 1 was fetched.
3. ``DuplicateMatchHint`` prefers ``url_canonical`` and only falls
   back to ``sha256_title_source_scoped`` (both columns required on
   staging). No title-only global match is ever emitted.
4. ``StagingDetail`` carries zero audit-only fields (no reviewer
   notes, no audit_log joins, no event metadata).

Tests use the ``review_client`` fixture (real aiosqlite via
dependency override + shared session_store) so RBAC and DB paths run
through the full ASGI stack.
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

from api.tables import metadata, reports_table, sources_table, staging_table


# ---------------------------------------------------------------------------
# Fixtures (mirror test_review_route.py — real aiosqlite overrides)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def real_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def review_client(
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


async def _insert_rows(
    engine: AsyncEngine,
    rows: list[dict],
    table: sa.Table = staging_table,
) -> list[int]:
    """Insert many rows, returning their ids in the provided order."""
    ids = []
    async with AsyncSession(engine, expire_on_commit=False) as s:
        for row in rows:
            result = await s.execute(
                sa.insert(table).values(**row).returning(table.c.id)
            )
            ids.append(result.scalar_one())
        await s.commit()
    return ids


def _staging_row(
    *,
    url_canonical: str,
    title: str | None = "t",
    url: str | None = None,
    created_at: dt.datetime | None = None,
    published: dt.datetime | None = None,
    source_id: int | None = None,
    sha256_title: str | None = None,
    status: str = "pending",
    lang: str | None = "en",
    confidence: float | None = None,
) -> dict:
    base = dt.datetime(2026, 4, 17, tzinfo=dt.timezone.utc)
    return {
        "url_canonical": url_canonical,
        "url": url or url_canonical,
        "title": title,
        "published": published or base,
        "created_at": created_at or base,
        "status": status,
        "source_id": source_id,
        "sha256_title": sha256_title,
        "lang": lang,
        "confidence": confidence,
    }


LIST_URL = "/api/v1/staging/review"
DETAIL_URL = "/api/v1/staging/{staging_id}"


async def _cookie(make_session_cookie, role: str = "analyst") -> str:
    return await make_session_cookie(roles=[role])


# ---------------------------------------------------------------------------
# RBAC — same triad as the review endpoint
# ---------------------------------------------------------------------------


class TestRBAC:
    async def test_list_without_session_401(
        self, review_client: AsyncClient
    ) -> None:
        resp = await review_client.get(LIST_URL)
        assert resp.status_code == 401

    async def test_list_policy_role_403(
        self, review_client: AsyncClient, make_session_cookie
    ) -> None:
        cookie = await _cookie(make_session_cookie, role="policy")
        resp = await review_client.get(
            LIST_URL, cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 403

    async def test_detail_without_session_401(
        self, review_client: AsyncClient
    ) -> None:
        resp = await review_client.get(DETAIL_URL.format(staging_id=1))
        assert resp.status_code == 401

    @pytest.mark.parametrize("role", ["analyst", "researcher", "admin"])
    async def test_list_allowed_roles_200(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        role: str,
    ) -> None:
        cookie = await _cookie(make_session_cookie, role=role)
        resp = await review_client.get(
            LIST_URL, cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# FIFO ordering — invariant #1
# ---------------------------------------------------------------------------


class TestFIFOOrdering:
    async def test_rows_ordered_by_created_at_ascending(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """FIFO primary sort: oldest created_at first."""
        t0 = dt.datetime(2026, 4, 10, tzinfo=dt.timezone.utc)
        ids = await _insert_rows(
            real_engine,
            [
                _staging_row(url_canonical="http://e/c", created_at=t0 + dt.timedelta(hours=2)),
                _staging_row(url_canonical="http://e/a", created_at=t0),
                _staging_row(url_canonical="http://e/b", created_at=t0 + dt.timedelta(hours=1)),
            ],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await review_client.get(
            LIST_URL, cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 200
        urls = [item["url_canonical"] for item in resp.json()["items"]]
        # a (t0) → b (t0+1h) → c (t0+2h), regardless of insert order.
        assert urls == ["http://e/a", "http://e/b", "http://e/c"]

    async def test_ties_broken_by_id_ascending(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """When created_at is identical, lower id comes first. This
        guards against the "bulk insert" case where the DB writes
        rows within a single timestamp granularity."""
        same_time = dt.datetime(2026, 4, 10, 12, 0, 0, tzinfo=dt.timezone.utc)
        ids = await _insert_rows(
            real_engine,
            [
                _staging_row(url_canonical="http://e/1", created_at=same_time),
                _staging_row(url_canonical="http://e/2", created_at=same_time),
                _staging_row(url_canonical="http://e/3", created_at=same_time),
            ],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await review_client.get(
            LIST_URL, cookies={"dprk_cti_session": cookie}
        )
        assert resp.status_code == 200
        returned_ids = [item["id"] for item in resp.json()["items"]]
        assert returned_ids == sorted(ids)


# ---------------------------------------------------------------------------
# Cursor pagination — invariant #2
# ---------------------------------------------------------------------------


class TestCursorPagination:
    async def test_keyset_cursor_paginates_without_overlap(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """Seed 5 rows, fetch limit=2 pages, verify (a) each page has
        the right rows, (b) next_cursor is present until the final
        page, (c) no row is repeated across pages, (d) the concat of
        all pages matches the FIFO order of all seeded rows."""
        base = dt.datetime(2026, 4, 10, tzinfo=dt.timezone.utc)
        rows = [
            _staging_row(
                url_canonical=f"http://e/{i}",
                created_at=base + dt.timedelta(hours=i),
            )
            for i in range(5)
        ]
        await _insert_rows(real_engine, rows)

        cookie = await _cookie(make_session_cookie)
        collected_urls: list[str] = []
        cursor: str | None = None
        page_count = 0

        while True:
            page_count += 1
            params: dict = {"limit": 2}
            if cursor is not None:
                params["cursor"] = cursor
            resp = await review_client.get(
                LIST_URL,
                params=params,
                cookies={"dprk_cti_session": cookie},
            )
            assert resp.status_code == 200
            body = resp.json()
            collected_urls.extend(item["url_canonical"] for item in body["items"])
            cursor = body["next_cursor"]
            if cursor is None:
                break
            # Safety: prevent infinite loop on a bug.
            assert page_count < 10

        # 5 rows across limit=2 → pages of 2, 2, 1 → 3 pages total.
        assert page_count == 3
        assert collected_urls == [f"http://e/{i}" for i in range(5)]
        # No duplicates.
        assert len(collected_urls) == len(set(collected_urls))

    async def test_next_cursor_null_on_last_page(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        await _insert_rows(
            real_engine,
            [_staging_row(url_canonical=f"http://e/{i}") for i in range(2)],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await review_client.get(
            LIST_URL,
            params={"limit": 50},
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 2
        assert body["next_cursor"] is None

    async def test_malformed_cursor_returns_400(
        self,
        review_client: AsyncClient,
        make_session_cookie,
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await review_client.get(
            LIST_URL,
            params={"cursor": "not-a-valid-cursor!!!"},
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "malformed_cursor"

    async def test_cursor_is_stable_against_late_inserts(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """Keyset cursor must not shift the page index when new rows
        arrive BEFORE the last-seen-row's (created_at, id) key."""
        base = dt.datetime(2026, 4, 10, tzinfo=dt.timezone.utc)
        # Seed 3 rows at t=0,1,2 hours.
        await _insert_rows(
            real_engine,
            [
                _staging_row(
                    url_canonical=f"http://original/{i}",
                    created_at=base + dt.timedelta(hours=i),
                )
                for i in range(3)
            ],
        )
        cookie = await _cookie(make_session_cookie)

        # Page 1: limit=2 → first two rows, cursor after row 2.
        resp = await review_client.get(
            LIST_URL,
            params={"limit": 2},
            cookies={"dprk_cti_session": cookie},
        )
        first_page = [i["url_canonical"] for i in resp.json()["items"]]
        cursor = resp.json()["next_cursor"]
        assert cursor is not None

        # Insert a LATE row with created_at in the past (t=-1) —
        # keyset cursor on (created_at, id) should NOT re-surface it
        # on page 2, because the cursor captured the "continue after
        # (t=1, id=2)" position.
        await _insert_rows(
            real_engine,
            [
                _staging_row(
                    url_canonical="http://late/row",
                    created_at=base - dt.timedelta(hours=1),
                )
            ],
        )

        resp = await review_client.get(
            LIST_URL,
            params={"cursor": cursor, "limit": 2},
            cookies={"dprk_cti_session": cookie},
        )
        second_page = [i["url_canonical"] for i in resp.json()["items"]]
        # Only the original row at t=2 should appear.
        assert second_page == ["http://original/2"]
        # The late-inserted row is NOT on page 2.
        assert "http://late/row" not in first_page + second_page


# ---------------------------------------------------------------------------
# Status filter
# ---------------------------------------------------------------------------


class TestStatusFilter:
    async def test_default_status_is_pending(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        await _insert_rows(
            real_engine,
            [
                _staging_row(url_canonical="http://e/a", status="pending"),
                _staging_row(url_canonical="http://e/b", status="rejected"),
                _staging_row(url_canonical="http://e/c", status="promoted"),
            ],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await review_client.get(
            LIST_URL, cookies={"dprk_cti_session": cookie}
        )
        statuses = {i["status"] for i in resp.json()["items"]}
        assert statuses == {"pending"}

    async def test_filter_by_rejected(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        await _insert_rows(
            real_engine,
            [
                _staging_row(url_canonical="http://e/a", status="pending"),
                _staging_row(url_canonical="http://e/b", status="rejected"),
            ],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await review_client.get(
            LIST_URL,
            params={"status": "rejected"},
            cookies={"dprk_cti_session": cookie},
        )
        urls = [i["url_canonical"] for i in resp.json()["items"]]
        assert urls == ["http://e/b"]

    async def test_unknown_status_is_422(
        self,
        review_client: AsyncClient,
        make_session_cookie,
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await review_client.get(
            LIST_URL,
            params={"status": "invalid"},
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Limit bounds
# ---------------------------------------------------------------------------


class TestLimitBounds:
    async def test_limit_below_1_is_422(
        self,
        review_client: AsyncClient,
        make_session_cookie,
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await review_client.get(
            LIST_URL,
            params={"limit": 0},
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422

    async def test_limit_above_200_is_422(
        self,
        review_client: AsyncClient,
        make_session_cookie,
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await review_client.get(
            LIST_URL,
            params={"limit": 201},
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Source join
# ---------------------------------------------------------------------------


class TestSourceJoin:
    async def test_source_name_surfaced_when_source_id_present(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        # Seed a source row first.
        async with AsyncSession(real_engine, expire_on_commit=False) as s:
            src = await s.execute(
                sa.insert(sources_table)
                .values(name="vendor-x", type="vendor")
                .returning(sources_table.c.id)
            )
            source_id = src.scalar_one()
            await s.commit()

        await _insert_rows(
            real_engine,
            [_staging_row(url_canonical="http://e/a", source_id=source_id)],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await review_client.get(
            LIST_URL, cookies={"dprk_cti_session": cookie}
        )
        item = resp.json()["items"][0]
        assert item["source_id"] == source_id
        assert item["source_name"] == "vendor-x"

    async def test_source_name_null_when_source_id_null(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        await _insert_rows(
            real_engine,
            [_staging_row(url_canonical="http://e/a", source_id=None)],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await review_client.get(
            LIST_URL, cookies={"dprk_cti_session": cookie}
        )
        item = resp.json()["items"][0]
        assert item["source_id"] is None
        assert item["source_name"] is None


# ---------------------------------------------------------------------------
# Detail endpoint
# ---------------------------------------------------------------------------


class TestDetailBasic:
    async def test_not_found_returns_404(
        self,
        review_client: AsyncClient,
        make_session_cookie,
    ) -> None:
        cookie = await _cookie(make_session_cookie)
        resp = await review_client.get(
            DETAIL_URL.format(staging_id=999),
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 404
        assert resp.json() == {"error": "not_found", "staging_id": 999}

    async def test_returns_full_staging_fields(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        ids = await _insert_rows(
            real_engine,
            [
                _staging_row(
                    url_canonical="http://e/x",
                    title="Detail Title",
                    sha256_title="a" * 64,
                    lang="ko",
                )
            ],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await review_client.get(
            DETAIL_URL.format(staging_id=ids[0]),
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == ids[0]
        assert body["title"] == "Detail Title"
        assert body["sha256_title"] == "a" * 64
        assert body["lang"] == "ko"
        assert body["status"] == "pending"
        assert body["decision_reason"] is None
        assert body["duplicate_matches"] == []

    async def test_detail_excludes_audit_only_fields(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """Plan §2.1 D1 / §2.2 C lock: row DTO must NOT carry audit-
        only fields. In particular, reviewer ``notes`` live only in
        audit_log.diff_jsonb.reviewer_notes — the detail endpoint
        must not join or expose them."""
        ids = await _insert_rows(
            real_engine, [_staging_row(url_canonical="http://e/x")]
        )
        cookie = await _cookie(make_session_cookie)
        resp = await review_client.get(
            DETAIL_URL.format(staging_id=ids[0]),
            cookies={"dprk_cti_session": cookie},
        )
        body = resp.json()
        # Positive: keys are bounded to the known StagingDetail shape.
        expected_keys = {
            "id",
            "created_at",
            "source_id",
            "source_name",
            "url",
            "url_canonical",
            "sha256_title",
            "title",
            "raw_text",
            "lang",
            "published",
            "summary",
            "confidence",
            "status",
            "reviewed_by",
            "reviewed_at",
            "decision_reason",
            "promoted_report_id",
            "error",
            "duplicate_matches",
        }
        assert set(body.keys()) == expected_keys
        # Negative — no stray audit / event-log fields.
        for forbidden in ("notes", "reviewer_notes", "audit_log", "action", "diff_jsonb"):
            assert forbidden not in body


# ---------------------------------------------------------------------------
# DuplicateMatchHint — invariant #3
# ---------------------------------------------------------------------------


class TestDuplicateMatchHints:
    async def _seed_source_and_report(
        self,
        engine: AsyncEngine,
        *,
        url_canonical: str,
        sha256_title: str,
        title: str = "existing title",
    ) -> tuple[int, int]:
        async with AsyncSession(engine, expire_on_commit=False) as s:
            src = await s.execute(
                sa.insert(sources_table)
                .values(name="vendor-x", type="vendor")
                .returning(sources_table.c.id)
            )
            source_id = src.scalar_one()
            rep = await s.execute(
                sa.insert(reports_table)
                .values(
                    published=dt.date(2026, 1, 1),
                    source_id=source_id,
                    title=title,
                    url="http://e/existing",
                    url_canonical=url_canonical,
                    sha256_title=sha256_title,
                )
                .returning(reports_table.c.id)
            )
            report_id = rep.scalar_one()
            await s.commit()
            return source_id, report_id

    async def test_url_canonical_match_surfaces_primary_hint(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        source_id, report_id = await self._seed_source_and_report(
            real_engine,
            url_canonical="http://dup.com/x",
            sha256_title="deadbeef" * 8,
        )
        ids = await _insert_rows(
            real_engine,
            [
                _staging_row(
                    url_canonical="http://dup.com/x",
                    sha256_title="different" + "x" * 55,
                    source_id=source_id,
                )
            ],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await review_client.get(
            DETAIL_URL.format(staging_id=ids[0]),
            cookies={"dprk_cti_session": cookie},
        )
        hints = resp.json()["duplicate_matches"]
        assert len(hints) == 1
        assert hints[0]["match_type"] == "url_canonical"
        assert hints[0]["report_id"] == report_id

    async def test_sha256_source_scoped_match_surfaces_secondary_hint(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """sha256_title + source_id both required. Different
        url_canonical so the primary path does NOT fire."""
        source_id, report_id = await self._seed_source_and_report(
            real_engine,
            url_canonical="http://existing.com/a",
            sha256_title="sharedhash" * 6 + "ab",
        )
        ids = await _insert_rows(
            real_engine,
            [
                _staging_row(
                    url_canonical="http://different.com/a",
                    sha256_title="sharedhash" * 6 + "ab",
                    source_id=source_id,
                )
            ],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await review_client.get(
            DETAIL_URL.format(staging_id=ids[0]),
            cookies={"dprk_cti_session": cookie},
        )
        hints = resp.json()["duplicate_matches"]
        assert len(hints) == 1
        assert hints[0]["match_type"] == "sha256_title_source_scoped"
        assert hints[0]["report_id"] == report_id

    async def test_sha256_match_suppressed_without_source_id(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """sha256_title match alone — NOT scoped to a source — must
        NOT surface. Generic headlines across vendors produce false
        positives (plan §2.1 D1 lock on source-scoped only)."""
        source_id, _ = await self._seed_source_and_report(
            real_engine,
            url_canonical="http://existing.com/a",
            sha256_title="orphanhash" * 6 + "xy",
        )
        # Staging row has matching sha256_title but NO source_id.
        ids = await _insert_rows(
            real_engine,
            [
                _staging_row(
                    url_canonical="http://different.com/a",
                    sha256_title="orphanhash" * 6 + "xy",
                    source_id=None,
                )
            ],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await review_client.get(
            DETAIL_URL.format(staging_id=ids[0]),
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.json()["duplicate_matches"] == []

    async def test_same_report_matches_both_emits_only_url_canonical(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        """A pre-existing report matching both criteria should be
        surfaced as url_canonical (stronger signal) only — dedup by
        report_id prevents duplicate hints pointing at the same row."""
        source_id, report_id = await self._seed_source_and_report(
            real_engine,
            url_canonical="http://both.com/a",
            sha256_title="bothhash!!" * 6 + "cd",
        )
        ids = await _insert_rows(
            real_engine,
            [
                _staging_row(
                    url_canonical="http://both.com/a",
                    sha256_title="bothhash!!" * 6 + "cd",
                    source_id=source_id,
                )
            ],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await review_client.get(
            DETAIL_URL.format(staging_id=ids[0]),
            cookies={"dprk_cti_session": cookie},
        )
        hints = resp.json()["duplicate_matches"]
        assert len(hints) == 1
        assert hints[0]["match_type"] == "url_canonical"
        assert hints[0]["report_id"] == report_id

    async def test_no_matches_returns_empty_list(
        self,
        review_client: AsyncClient,
        make_session_cookie,
        real_engine: AsyncEngine,
    ) -> None:
        ids = await _insert_rows(
            real_engine,
            [_staging_row(url_canonical="http://fresh.com/x")],
        )
        cookie = await _cookie(make_session_cookie)
        resp = await review_client.get(
            DETAIL_URL.format(staging_id=ids[0]),
            cookies={"dprk_cti_session": cookie},
        )
        assert resp.json()["duplicate_matches"] == []
