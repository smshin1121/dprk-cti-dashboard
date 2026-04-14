"""Audit log writer.

Every authentication event (login_success, login_failure, logout) is
persisted to the ``audit_log`` table created by migration 0001. We use raw
SQL because no ORM models exist yet — keeping this module dependency-free
makes it easy to reuse from other routers.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def write_audit(
    db_session: AsyncSession,
    *,
    actor: str,
    action: str,
    entity: str = "auth",
    entity_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Insert a single row into ``audit_log``.

    Args:
        db_session: An async SQLAlchemy session (typically wired via Depends).
        actor: User identifier (e.g. ``sub`` or email). Use ``"anonymous"``
            for failed logins where no identity exists yet.
        action: Short verb describing the event (``login_success``, ``logout``).
        entity: Entity type the action targets. Defaults to ``"auth"``.
        entity_id: Optional identifier of the affected entity.
        extra: Arbitrary JSON payload (IP, user agent, error reason, etc.).
    """
    payload = json.dumps(extra or {})
    await db_session.execute(
        text(
            """
            INSERT INTO audit_log (actor, action, entity, entity_id, timestamp, diff_jsonb)
            VALUES (:actor, :action, :entity, :entity_id, NOW(), CAST(:diff AS JSONB))
            """
        ),
        {
            "actor": actor,
            "action": action,
            "entity": entity,
            "entity_id": entity_id,
            "diff": payload,
        },
    )
    await db_session.commit()
