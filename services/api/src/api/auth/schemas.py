"""Pydantic models shared across the auth module."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# Realm roles enforced at the router-level RBAC layer (see ``_READ_ROLES``
# and ``ALLOWED_REVIEWER_ROLES`` in ``api.routers.*``). Single source of
# truth for the type system AND the runtime filter in
# ``api.auth.jwt_verifier`` — ``KNOWN_ROLES`` there is derived from
# ``typing.get_args(KnownRole)``, so adding a role here automatically
# updates the filter without needing two synchronized constants.
#
# The Phase 0 deferral originally listed three roles ("analyst", "admin",
# "policy") based on an early §9.3 sketch. The router-level RBAC matrix
# already accepts five — including ``researcher`` (read+review) and
# ``soc`` (read). Pre-PR ``KNOWN_ROLES`` filtered the latter two out at
# token extraction, so a user granted only ``researcher`` or ``soc`` in
# Keycloak would arrive at ``require_role`` with an empty list and 403
# everywhere despite being on the allowlist. Closing the deferral with
# the wider set fixes that pre-existing filter/router inconsistency.
KnownRole = Literal["analyst", "admin", "policy", "researcher", "soc"]


class CurrentUser(BaseModel):
    """Identity surfaced to route handlers via Depends(verify_token)."""

    sub: str
    email: str
    name: str | None = None
    roles: list[KnownRole]


class SessionData(BaseModel):
    """Server-side session record stored in Redis under ``session:<sid>``."""

    sub: str
    email: str
    name: str | None = None
    roles: list[KnownRole]
    created_at: datetime
    last_activity: datetime
