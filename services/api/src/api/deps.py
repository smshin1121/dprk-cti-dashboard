"""
FastAPI dependency stubs.

verify_token is intentionally fail-closed: every protected route returns 501
until a real JWT/OIDC implementation replaces this stub.  This makes it
physically impossible to accidentally expose authenticated endpoints as
open-access.

TODO: replace with real JWT validation using authlib (already in pyproject.toml).
"""

from fastapi import HTTPException


def verify_token() -> None:
    """Stub auth dependency.  Replace with real JWT validation before launch."""
    raise HTTPException(
        status_code=501,
        detail="Auth not yet implemented — this endpoint requires authentication.",
    )
