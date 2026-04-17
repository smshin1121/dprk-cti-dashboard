"""Staging → production promote path (PR #10 Phase 2.1).

Submodules:
- ``errors``: domain-level exceptions the router maps to HTTP status codes.
- ``repositories``: ON CONFLICT upsert helpers for each production table
  touched by a promote (plan §2.3). Postgres is the canonical target;
  sqlite dialect support exists only so unit tests can exercise the
  same conflict-return-id flow without a live PG instance.
- ``service`` (Group D): the single-transaction orchestration
  ``promote_staging_row`` + reject path (plan §2.2 A).
"""
