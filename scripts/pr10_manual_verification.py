"""PR #10 manual verification harness (plan §6 acceptance items 5-6).

Runs two scenarios against the real local Postgres + forged signed
session cookie, then shells out to the worker DQ CLI to verify
``review.backlog_size`` + ``review.avg_latency_hours`` write rows to
``dq_events``.

Usage (Windows bash):
  cd services/api
  POSTGRES_SMOKE_URL="postgresql+psycopg_async://postgres:CHANGE_ME@localhost:5434/dprk_cti" \
  python -m uv run python ../../scripts/pr10_manual_verification.py

Why forged session cookie, not real OIDC:
  The dev realm has ``directAccessGrantsEnabled=false`` so password
  grant for CLI token acquisition is unavailable; a browser-based
  authorization-code flow is required for a real OIDC session, which
  is not automatable in this shell context. The api's session cookie
  is verified end-to-end by the session-store tests (P1.1), and the
  cookie signer + RBAC dep chain is exercised by every integration
  test in test_review_route.py / test_staging_routes.py. What this
  script verifies incrementally is the FULL HTTP stack against REAL
  Postgres: router → dep chain → real session store → real DB
  transaction → real audit/staging state.

Evidence artifacts written to docs/plans/pr10-evidence/:
  approve-response.json      — 200 body
  reject-response.json       — 200 body
  approve-db-state.txt       — psql staging/audit_log state
  reject-db-state.txt        — psql staging/audit_log state
  dq-events-review.txt       — dq_events review.* rows
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# Running under the api venv — add worker src so the review.* expectations
# (which live in services/worker/src/worker/...) can be imported inline.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKER_SRC = _REPO_ROOT / "services" / "worker" / "src"
if str(_WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(_WORKER_SRC))


_ENV = {
    "APP_ENV": "test",
    "DATABASE_URL": "postgresql+psycopg://postgres:CHANGE_ME@localhost:5434/dprk_cti",
    "REDIS_URL": "redis://localhost:6379/0",
    "JWT_SECRET": "pr10-manual-verification-secret-32chars",
    "OIDC_CLIENT_ID": "dprk-cti",
    "OIDC_CLIENT_SECRET": "manual-verification-placeholder",
    "OIDC_ISSUER_URL": "http://keycloak.test/realms/dprk",
    "OIDC_REDIRECT_BASE_URL": "http://localhost:8000",
    "SESSION_SIGNING_KEY": "pr10-manual-verification-signing-key32",
    "SESSION_COOKIE_NAME": "dprk_cti_session",
    "SESSION_COOKIE_SECURE": "false",
    "SESSION_COOKIE_SAMESITE": "lax",
    "CORS_ORIGINS": "http://localhost:3000",
}
for k, v in _ENV.items():
    os.environ.setdefault(k, v)


from api.auth.schemas import SessionData  # noqa: E402
from api.auth.session import SessionStore  # noqa: E402
from api.config import get_settings  # noqa: E402
from api.tables import (  # noqa: E402
    audit_log_table,
    reports_table,
    sources_table,
    staging_table,
)


EVIDENCE_DIR = Path(__file__).resolve().parents[1] / "docs" / "plans" / "pr10-evidence"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

PG_URL_SYNC = "postgresql://postgres:CHANGE_ME@localhost:5434/dprk_cti"
PG_URL_ASYNC = "postgresql+psycopg_async://postgres:CHANGE_ME@localhost:5434/dprk_cti"
PG_URL_PSYCOPG = "postgresql+psycopg://postgres:CHANGE_ME@localhost:5434/dprk_cti"


def _psql(sql: str) -> str:
    """Run a SQL command against the local docker PG via psql and
    return the captured stdout. Used for capturing evidence in a form
    a reviewer can paste verbatim into the PR body.

    ``encoding="utf-8"`` is forced because the Windows default cp949
    chokes on en/em-dashes that appear in psql output of rows carrying
    them (known pitfall per project memory)."""
    result = subprocess.run(
        [
            "docker",
            "exec",
            "dprk-cti-db-1",
            "psql",
            "-U",
            "postgres",
            "-d",
            "dprk_cti",
            "-c",
            sql,
        ],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return result.stdout


async def _run() -> None:
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import insert, select, text
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    import fakeredis.aioredis
    from itsdangerous import URLSafeTimedSerializer

    # -------------------------------------------------------------------
    # Fresh DB state
    # -------------------------------------------------------------------
    _psql(
        "TRUNCATE staging, reports, sources, audit_log, dq_events "
        "RESTART IDENTITY CASCADE;"
    )
    print("[+] TRUNCATEd staging/reports/sources/audit_log/dq_events")

    # -------------------------------------------------------------------
    # Session store (fakeredis so we don't need a real Redis)
    # -------------------------------------------------------------------
    redis = fakeredis.aioredis.FakeRedis()
    signer = URLSafeTimedSerializer(
        _ENV["SESSION_SIGNING_KEY"], salt="dprk-cti-session-v1"
    )
    store = SessionStore(redis=redis, signer=signer, ttl_seconds=3600)

    async def _cookie_for(role: str, sub: str = "analyst-manual-verif") -> str:
        now = datetime.now(timezone.utc)
        data = SessionData(
            sub=sub,
            email=f"{sub}@example.test",
            name=f"Manual Verification ({role})",
            roles=[role],
            created_at=now,
            last_activity=now,
        )
        return await store.create(data)

    # -------------------------------------------------------------------
    # ASGI client wiring
    # -------------------------------------------------------------------
    engine = create_async_engine(PG_URL_ASYNC, future=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db():
        async with sessionmaker() as session:
            yield session

    from api.auth.session import get_session_store
    from api.db import get_db
    from api.main import app

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_session_store] = lambda: store

    # -------------------------------------------------------------------
    # Seed two pending staging rows (one for approve, one for reject)
    # -------------------------------------------------------------------
    async with sessionmaker() as session:
        result = await session.execute(
            insert(staging_table)
            .values(
                url_canonical="http://verif.example/approve",
                url="http://verif.example/approve",
                title="PR10 manual verif - approve target",
                published=datetime(2026, 4, 17, tzinfo=timezone.utc),
                status="pending",
            )
            .returning(staging_table.c.id)
        )
        approve_id = result.scalar_one()

        result = await session.execute(
            insert(staging_table)
            .values(
                url_canonical="http://verif.example/reject",
                url="http://verif.example/reject",
                title="PR10 manual verif - reject target",
                published=datetime(2026, 4, 17, tzinfo=timezone.utc),
                status="pending",
            )
            .returning(staging_table.c.id)
        )
        reject_id = result.scalar_one()
        await session.commit()
    print(f"[+] Seeded staging rows: approve_id={approve_id} reject_id={reject_id}")

    # -------------------------------------------------------------------
    # Exercise the endpoint
    # -------------------------------------------------------------------
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        cookie = await _cookie_for("analyst")

        # APPROVE
        resp_approve = await client.post(
            f"/api/v1/reports/review/{approve_id}",
            cookies={"dprk_cti_session": cookie},
            json={
                "decision": "approve",
                "notes": "manual verif — approve path",
            },
        )
        approve_body = resp_approve.json()
        print(f"[+] APPROVE -> {resp_approve.status_code} {approve_body}")
        (EVIDENCE_DIR / "approve-response.json").write_text(
            json.dumps(
                {
                    "http_status": resp_approve.status_code,
                    "body": approve_body,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        # Capture DB state for approve.
        approve_evidence = (
            "-- staging row after approve --\n"
            + _psql(
                f"SELECT id, status, reviewed_by, promoted_report_id, "
                f"decision_reason FROM staging WHERE id={approve_id};"
            )
            + "\n-- audit_log for approved row --\n"
            + _psql(
                f"SELECT actor, action, entity, entity_id, "
                f"diff_jsonb->'attached_existing' AS attached_existing, "
                f"diff_jsonb->>'reviewer_notes' AS reviewer_notes "
                f"FROM audit_log WHERE action='REPORT_PROMOTED';"
            )
            + "\n-- reports row inserted --\n"
            + _psql(
                "SELECT id, title, url_canonical, source_id FROM reports "
                "WHERE url_canonical='http://verif.example/approve';"
            )
        )
        (EVIDENCE_DIR / "approve-db-state.txt").write_text(
            approve_evidence, encoding="utf-8"
        )
        print("[+] Wrote approve-db-state.txt")

        # REJECT
        resp_reject = await client.post(
            f"/api/v1/reports/review/{reject_id}",
            cookies={"dprk_cti_session": cookie},
            json={
                "decision": "reject",
                "decision_reason": "manual verif — duplicate-check feedback",
                "notes": "reviewer-internal note, audit-only",
            },
        )
        reject_body = resp_reject.json()
        print(f"[+] REJECT -> {resp_reject.status_code} {reject_body}")
        (EVIDENCE_DIR / "reject-response.json").write_text(
            json.dumps(
                {
                    "http_status": resp_reject.status_code,
                    "body": reject_body,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        reject_evidence = (
            "-- staging row after reject --\n"
            + _psql(
                f"SELECT id, status, reviewed_by, promoted_report_id, "
                f"decision_reason FROM staging WHERE id={reject_id};"
            )
            + "\n-- audit_log for rejected row --\n"
            + _psql(
                f"SELECT actor, action, entity, entity_id, "
                f"diff_jsonb->>'decision_reason' AS decision_reason, "
                f"diff_jsonb->>'reviewer_notes' AS reviewer_notes "
                f"FROM audit_log WHERE action='STAGING_REJECTED';"
            )
        )
        (EVIDENCE_DIR / "reject-db-state.txt").write_text(
            reject_evidence, encoding="utf-8"
        )
        print("[+] Wrote reject-db-state.txt")

        # Negative assertions — verify audit_log has EXACTLY 2 rows and
        # NEITHER is STAGING_APPROVED.
        audit_count = int(
            _psql("SELECT COUNT(*) FROM audit_log;").strip().split("\n")[-2].strip()
        )
        approved_events = int(
            _psql(
                "SELECT COUNT(*) FROM audit_log WHERE action='STAGING_APPROVED';"
            )
            .strip()
            .split("\n")[-2]
            .strip()
        )
        assert audit_count == 2, f"expected 2 audit rows, got {audit_count}"
        assert approved_events == 0, (
            f"STAGING_APPROVED MUST NOT be emitted; got {approved_events}"
        )
        print("[+] Audit counts verified: 2 rows total, 0 STAGING_APPROVED")

    app.dependency_overrides.clear()
    await engine.dispose()

    # -------------------------------------------------------------------
    # Run worker DQ CLI → verify review.* rows land in dq_events.
    # -------------------------------------------------------------------
    print("\n[+] Running review.* expectations inline ...")
    # Invoked inline (not via the DQ CLI subprocess) because the worker
    # CLI's asyncio.run path hits the Windows ProactorEventLoop + psycopg
    # async incompatibility — a known repo pitfall documented in project
    # memory. The api-integration CI job runs on Linux so the normal CLI
    # works there; this local script already sets SelectorEventLoopPolicy
    # at module top, so invoking the expectations in-process avoids the
    # re-entrant event loop bug.
    import uuid as _uuid

    from worker.data_quality.expectations.review_metrics import (
        review_avg_latency_hours,
        review_backlog_size,
    )
    from worker.data_quality.sinks import DbSink

    engine2 = create_async_engine(PG_URL_ASYNC, future=True)
    sessionmaker2 = async_sessionmaker(engine2, expire_on_commit=False)

    dq_run_id = _uuid.uuid4()
    async with sessionmaker2() as s:
        backlog_result = await review_backlog_size.check(s)
        latency_result = await review_avg_latency_hours.check(s)
        db_sink = DbSink(s, dq_run_id)
        await db_sink.write([backlog_result, latency_result])
        await s.commit()
    await engine2.dispose()

    print(
        f"[+] review.backlog_size: severity={backlog_result.severity} "
        f"observed={backlog_result.observed} rows={backlog_result.observed_rows}"
    )
    print(
        f"[+] review.avg_latency_hours: severity={latency_result.severity} "
        f"observed={latency_result.observed} rows={latency_result.observed_rows}"
    )

    dq_events_rows = _psql(
        "SELECT expectation, severity, observed, observed_rows, "
        "detail_jsonb::text AS detail "
        "FROM dq_events WHERE expectation LIKE 'review.%' "
        "ORDER BY expectation;"
    )
    dq_evidence = (
        f"-- review.* expectations invoked inline (Windows event-loop "
        f"pitfall workaround) with run_id={dq_run_id} --\n\n"
        f"-- dq_events review.* rows --\n{dq_events_rows}\n"
        f"-- backlog result --\n"
        f"severity={backlog_result.severity} observed={backlog_result.observed} "
        f"observed_rows={backlog_result.observed_rows} "
        f"threshold={backlog_result.threshold}\n"
        f"detail={backlog_result.detail}\n\n"
        f"-- latency result --\n"
        f"severity={latency_result.severity} observed={latency_result.observed} "
        f"observed_rows={latency_result.observed_rows} "
        f"threshold={latency_result.threshold}\n"
        f"detail={latency_result.detail}\n"
    )
    (EVIDENCE_DIR / "dq-events-review.txt").write_text(
        dq_evidence, encoding="utf-8"
    )
    print("[+] Wrote dq-events-review.txt")
    print("\n=== PR #10 manual verification complete ===")
    print(f"Evidence directory: {EVIDENCE_DIR}")


if __name__ == "__main__":
    asyncio.run(_run())
