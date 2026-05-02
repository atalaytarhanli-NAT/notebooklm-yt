from fastapi import Cookie, Header, HTTPException, status

from .config import settings

COOKIE_NAME = "app_token"


async def require_token(
    authorization: str | None = Header(default=None),
    app_token: str | None = Cookie(default=None),
) -> None:
    if not settings.app_token or settings.app_token == "change-me-in-production":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="APP_TOKEN env var is not configured on the server",
        )
    token: str | None = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    elif app_token:
        token = app_token
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    if token != settings.app_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
