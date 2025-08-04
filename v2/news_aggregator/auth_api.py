"""Authentication API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBasicCredentials
from pydantic import BaseModel

from .security import (
    authenticate_admin_basic, 
    create_jwt_token, 
    get_current_user_jwt,
    SecurityLevel,
    get_security_info,
    limiter
)

router = APIRouter(prefix="/auth", tags=["authentication"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int  # seconds
    level: str


class UserInfo(BaseModel):
    username: str
    level: str
    expires_at: str


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(authenticate_admin_basic)
):
    """Login with username/password and get JWT token."""
    # Create JWT token
    token = create_jwt_token(credentials.username, SecurityLevel.ADMIN)
    
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=24 * 3600,  # 24 hours
        level=SecurityLevel.ADMIN
    )


@router.get("/me", response_model=UserInfo)
async def get_current_user_info(
    user: dict = Depends(get_current_user_jwt)
):
    """Get current user information."""
    from datetime import datetime, timezone
    
    expires_at = datetime.fromtimestamp(user["exp"], tz=timezone.utc)
    
    return UserInfo(
        username=user["sub"],
        level=user["level"],
        expires_at=expires_at.isoformat()
    )


@router.post("/refresh")
async def refresh_token(
    user: dict = Depends(get_current_user_jwt)
):
    """Refresh JWT token."""
    # Create new token with same level
    new_token = create_jwt_token(user["sub"], user["level"])
    
    return TokenResponse(
        access_token=new_token,
        token_type="bearer",
        expires_in=24 * 3600,
        level=user["level"]
    )


@router.get("/security-status")
async def security_status():
    """Get security configuration status."""
    return get_security_info()


@router.post("/logout")
async def logout():
    """Logout (client should discard token)."""
    return {"message": "Logged out successfully. Please discard your token."}