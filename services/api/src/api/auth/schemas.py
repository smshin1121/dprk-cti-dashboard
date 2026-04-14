"""Pydantic models shared across the auth module."""

from datetime import datetime

from pydantic import BaseModel


class CurrentUser(BaseModel):
    """Identity surfaced to route handlers via Depends(verify_token)."""

    sub: str
    email: str
    name: str | None = None
    roles: list[str]


class SessionData(BaseModel):
    """Server-side session record stored in Redis under ``session:<sid>``."""

    sub: str
    email: str
    name: str | None = None
    roles: list[str]
    created_at: datetime
    last_activity: datetime
