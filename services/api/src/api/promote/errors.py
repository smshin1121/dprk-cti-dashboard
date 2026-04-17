"""Domain-level exceptions for the promote path.

The router (Group F) catches these and maps to HTTP status codes. Each
exception carries the minimal data the router needs to build the 409
``AlreadyDecidedError`` body or the 404 not-found response.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class PromoteError(Exception):
    """Base class for all promote-path failures raised by
    ``api.promote.service`` and caught by the router."""


@dataclass
class StagingNotFoundError(PromoteError):
    """Raised when the staging_id path parameter points at no row.

    Router maps to 404.
    """

    staging_id: int

    def __str__(self) -> str:  # pragma: no cover — trivial
        return f"staging row {self.staging_id} not found"


@dataclass
class StagingAlreadyDecidedError(PromoteError):
    """Raised when the staging row is not in ``pending`` status at the
    moment of decision (plan §2.2 B — SELECT FOR UPDATE + conditional
    UPDATE race detection).

    The router maps this to 409 and serializes the fields via
    ``api.schemas.review.AlreadyDecidedError``. ``current_status`` is
    narrowed to the reachable post-decision values by
    ``DecidedStatus`` in the DTO — constructor callers must only pass
    ``"promoted"`` or ``"rejected"``.
    """

    staging_id: int
    current_status: str  # narrowed to DecidedStatus at the router edge
    decided_by: str
    decided_at: datetime

    def __str__(self) -> str:  # pragma: no cover — trivial
        return (
            f"staging row {self.staging_id} already decided "
            f"(status={self.current_status}, by={self.decided_by})"
        )


@dataclass
class PromoteValidationError(PromoteError):
    """Raised when the staging row is in a shape the promote path
    cannot materialize into ``reports`` — e.g. a missing NOT NULL
    column value that migration 0001 requires (``published``,
    ``title``, ``url``, ``url_canonical``, ``sha256_title``).

    Router maps to 422. The ``reason`` string surfaces in the 422 body
    so the reviewer can see what the staging row lacks.
    """

    staging_id: int
    reason: str

    def __str__(self) -> str:  # pragma: no cover — trivial
        return f"staging row {self.staging_id} cannot be promoted: {self.reason}"


__all__ = [
    "PromoteError",
    "PromoteValidationError",
    "StagingAlreadyDecidedError",
    "StagingNotFoundError",
]
