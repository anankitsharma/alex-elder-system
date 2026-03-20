"""JWT authentication + role-based access control for multi-user system.

Usage:
    from app.middleware.auth import get_current_user, RequireRole, Role

    # Any authenticated user
    @router.get("/me")
    async def me(user: User = Depends(get_current_user)):
        ...

    # Require specific role (or higher)
    @router.post("/orders", dependencies=[Depends(RequireRole(Role.TRADER))])
    async def create_order(user: User = Depends(get_current_user)):
        ...
"""

from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from fastapi import Depends, HTTPException, WebSocket, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.config import settings
from app.database import async_session
from app.models.user import User

# Password hashing — use bcrypt directly (passlib broken with bcrypt>=4.1)
import bcrypt as _bcrypt

# OAuth2 scheme — extracts token from Authorization: Bearer <token>
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

ALGORITHM = "HS256"


# ── Role Enum ────────────────────────────────────────────────

class Role(str, Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    TRADER = "trader"
    VIEWER = "viewer"


# Role hierarchy: lower number = higher privilege
ROLE_HIERARCHY = {
    Role.SUPER_ADMIN: 0,
    Role.ADMIN: 1,
    Role.TRADER: 2,
    Role.VIEWER: 3,
}


# ── Token Creation ───────────────────────────────────────────

def create_access_token(user_id: int, role: str, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


# ── Password Helpers ─────────────────────────────────────────

def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


# ── User Extraction ──────────────────────────────────────────

async def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> User:
    """FastAPI dependency — extract and validate user from JWT.

    Raises 401 if token is missing, invalid, or user doesn't exist.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub", 0))
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired or invalid",
            headers={"WWW-Authenticate": "Bearer"},
        )

    async with async_session() as session:
        result = await session.execute(
            select(User).options(joinedload(User.role)).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    return user


async def get_current_user_optional(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[User]:
    """Like get_current_user but returns None instead of raising on missing token."""
    if not token:
        return None
    try:
        return await get_current_user(token)
    except HTTPException:
        return None


async def get_ws_user(websocket: WebSocket) -> Optional[User]:
    """Extract user from WebSocket query param ?token=JWT."""
    token = websocket.query_params.get("token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub", 0))
        if not user_id:
            return None
        async with async_session() as session:
            result = await session.execute(
                select(User).options(joinedload(User.role)).where(User.id == user_id)
            )
            return result.scalar_one_or_none()
    except Exception:
        return None


# ── Role Checking ────────────────────────────────────────────

class RequireRole:
    """FastAPI dependency — check user has required role (or higher in hierarchy).

    Usage:
        @router.post("/users", dependencies=[Depends(RequireRole(Role.SUPER_ADMIN))])
    """

    def __init__(self, min_role: Role):
        self.min_role = min_role

    async def __call__(self, user: User = Depends(get_current_user)) -> User:
        user_role_name = user.role.name if user.role else "viewer"
        user_level = ROLE_HIERARCHY.get(user_role_name, 99)
        required_level = ROLE_HIERARCHY.get(self.min_role, 0)

        if user_level > required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Requires '{self.min_role.value}' role or higher.",
            )
        return user
