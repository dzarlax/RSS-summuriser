"""Enhanced security system with JWT tokens and rate limiting."""

import jwt
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from fastapi import HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPBasicCredentials, HTTPBasic
from fastapi.security.utils import get_authorization_scheme_param
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .config import settings

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# JWT Configuration
JWT_SECRET_KEY = settings.admin_password or secrets.token_urlsafe(32)
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# Security schemes
security_basic = HTTPBasic()
security_bearer = HTTPBearer(auto_error=False)

# Failed login tracking
failed_attempts: Dict[str, int] = {}
lockout_until: Dict[str, datetime] = {}

LOCKOUT_THRESHOLD = 5  # Failed attempts before lockout
LOCKOUT_DURATION = 300  # 5 minutes


class SecurityLevel:
    """Security levels for different endpoints."""
    PUBLIC = "public"
    API_READ = "api_read"
    API_WRITE = "api_write"
    ADMIN = "admin"


def create_jwt_token(username: str, level: str = SecurityLevel.ADMIN) -> str:
    """Create JWT token for authenticated user."""
    payload = {
        "sub": username,
        "level": level,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.now(timezone.utc),
        "type": "access"
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify and decode JWT token."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def is_ip_locked(ip: str) -> bool:
    """Check if IP is locked due to failed attempts."""
    if ip in lockout_until:
        if datetime.now() < lockout_until[ip]:
            return True
        else:
            # Lockout expired, reset
            del lockout_until[ip]
            failed_attempts.pop(ip, None)
    return False


def record_failed_attempt(ip: str):
    """Record failed login attempt."""
    failed_attempts[ip] = failed_attempts.get(ip, 0) + 1
    
    if failed_attempts[ip] >= LOCKOUT_THRESHOLD:
        lockout_until[ip] = datetime.now() + timedelta(seconds=LOCKOUT_DURATION)


def reset_failed_attempts(ip: str):
    """Reset failed attempts for IP."""
    failed_attempts.pop(ip, None)
    lockout_until.pop(ip, None)


@limiter.limit("10/minute")
async def authenticate_admin_basic(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(security_basic)
) -> str:
    """Authenticate admin with HTTP Basic (for login endpoint)."""
    client_ip = get_remote_address(request)
    
    # Check if IP is locked
    if is_ip_locked(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Try again in {LOCKOUT_DURATION // 60} minutes."
        )
    
    # Check admin password configured
    if not settings.admin_password:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Admin authentication not configured"
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
        record_failed_attempt(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    
    # Success - reset failed attempts
    reset_failed_attempts(client_ip)
    return credentials.username


async def get_current_user_jwt(request: Request) -> Dict[str, Any]:
    """Get current user from JWT token."""
    authorization: str = request.headers.get("Authorization")
    
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    scheme, token = get_authorization_scheme_param(authorization)
    
    if scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication scheme",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    payload = verify_jwt_token(token)
    
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return payload


async def require_admin(user: Dict = Depends(get_current_user_jwt)) -> Dict[str, Any]:
    """Require admin level access."""
    if user.get("level") != SecurityLevel.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return user


async def require_api_write(user: Dict = Depends(get_current_user_jwt)) -> Dict[str, Any]:
    """Require API write access."""
    level = user.get("level")
    if level not in [SecurityLevel.API_WRITE, SecurityLevel.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API write access required"
        )
    return user


async def require_api_read(user: Dict = Depends(get_current_user_jwt)) -> Dict[str, Any]:
    """Require API read access."""
    level = user.get("level")
    if level not in [SecurityLevel.API_READ, SecurityLevel.API_WRITE, SecurityLevel.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API access required"
        )
    return user


def get_security_info() -> Dict[str, Any]:
    """Get security configuration info."""
    return {
        "admin_auth_configured": bool(settings.admin_password),
        "jwt_expiration_hours": JWT_EXPIRATION_HOURS,
        "rate_limiting_enabled": True,
        "lockout_threshold": LOCKOUT_THRESHOLD,
        "lockout_duration_minutes": LOCKOUT_DURATION // 60,
        "failed_attempts_count": len(failed_attempts),
        "locked_ips_count": len(lockout_until)
    }