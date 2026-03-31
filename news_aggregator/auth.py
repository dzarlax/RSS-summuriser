"""Authentication middleware for admin panel."""

import secrets
from typing import Optional

from fastapi import HTTPException, Depends, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .config import settings

security = HTTPBasic(auto_error=False)


def get_current_admin_user(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Depends(security),
) -> str:
    """Verify admin credentials (Authentik ForwardAuth, HTTP Basic, or JWT cookie)."""
    # Authentik ForwardAuth: trust X-authentik-username when reverse proxy handles auth
    if settings.trust_forward_auth:
        authentik_user = request.headers.get("X-authentik-username")
        if authentik_user:
            return authentik_user

    # Check if admin password is configured
    if not settings.admin_password:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Admin authentication not configured. Please set ADMIN_PASSWORD environment variable."
        )

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    # Verify credentials
    is_correct_username = secrets.compare_digest(
        credentials.username.encode("utf8"),
        settings.admin_username.encode("utf8")
    )
    is_correct_password = secrets.compare_digest(
        credentials.password.encode("utf8"),
        settings.admin_password.encode("utf8")
    )

    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username


def check_admin_configured() -> bool:
    """Check if admin authentication is properly configured."""
    return bool(settings.admin_password)


def get_admin_auth_status() -> dict:
    """Get admin authentication status for debugging."""
    return {
        "admin_auth_configured": check_admin_configured(),
        "admin_username": settings.admin_username,
        "password_set": bool(settings.admin_password)
    }