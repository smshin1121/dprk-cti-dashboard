from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/login")
def login() -> dict[str, str]:
    """§7.6 OIDC login entry point (Keycloak redirect)."""
    return {"status": "todo", "detail": "OIDC login scaffold"}


@router.get("/me")
def me() -> JSONResponse:
    """§7.6 Return the current authenticated user profile."""
    return JSONResponse(
        status_code=501,
        content={"status": "not_implemented", "endpoint": "auth.me"},
    )


@router.get("/callback")
def callback() -> dict[str, str]:
    # TODO (SECURITY): Before this goes to production the real implementation MUST:
    #   1. Verify the `state` query parameter matches the value stored in the
    #      user's session to prevent CSRF attacks on the OAuth2 callback.
    #   2. Exchange the authorization `code` for tokens using authlib's
    #      AsyncOAuth2Client and validate the id_token signature + claims.
    #   3. Set a signed, HttpOnly, SameSite=Strict session cookie (never expose
    #      raw tokens to JavaScript).
    return {"status": "todo", "detail": "OIDC callback scaffold"}
