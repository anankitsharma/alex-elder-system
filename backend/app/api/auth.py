"""Authentication API — login, register, profile, broker credentials."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.config import settings
from app.database import async_session
from app.middleware.auth import (
    create_access_token, hash_password, verify_password,
    get_current_user, RequireRole, Role,
)
from app.models.user import User, Role as RoleModel, AccessRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Request/Response Schemas ─────────────────────────────────

class RegisterRequest(BaseModel):
    email: str
    username: str
    password: str
    full_name: str = ""


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    full_name: str
    role: str
    trading_mode: str
    is_active: bool
    approved_for_live: bool
    max_risk_per_trade_pct: float
    max_portfolio_risk_pct: float
    min_signal_score: int
    paper_starting_capital: float
    created_at: Optional[str] = None


# ── Endpoints ────────────────────────────────────────────────

@router.post("/register", response_model=UserResponse,
             dependencies=[Depends(RequireRole(Role.SUPER_ADMIN))])
async def register(req: RegisterRequest, admin: User = Depends(get_current_user)):
    """Create a new user. Super Admin only."""
    async with async_session() as session:
        # Check for existing email/username
        existing = await session.execute(
            select(User).where((User.email == req.email) | (User.username == req.username))
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email or username already exists")

        # Default role: trader (id=3)
        trader_role = await session.execute(select(RoleModel).where(RoleModel.name == "trader"))
        role = trader_role.scalar_one_or_none()

        user = User(
            email=req.email,
            username=req.username,
            hashed_password=hash_password(req.password),
            full_name=req.full_name,
            role_id=role.id if role else 3,
            trading_mode="PAPER",
            created_by=admin.id,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        return _user_response(user)


@router.post("/login", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends()):
    """Login with username/email + password. Returns JWT."""
    async with async_session() as session:
        result = await session.execute(
            select(User).options(joinedload(User.role)).where(
                (User.username == form.username) | (User.email == form.username)
            )
        )
        user = result.scalar_one_or_none()

    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    role_name = user.role.name if user.role else "viewer"
    token = create_access_token(user.id, role_name)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    """Get current user profile."""
    return _user_response(user)


@router.post("/request-live")
async def request_live_access(user: User = Depends(get_current_user)):
    """Request upgrade from PAPER to LIVE trading. Requires admin approval."""
    if user.approved_for_live:
        raise HTTPException(status_code=400, detail="Already approved for live trading")

    async with async_session() as session:
        # Check for existing pending request
        existing = await session.execute(
            select(AccessRequest).where(
                AccessRequest.user_id == user.id,
                AccessRequest.request_type == "live_trading",
                AccessRequest.status == "PENDING",
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Request already pending")

        req = AccessRequest(
            user_id=user.id,
            request_type="live_trading",
        )
        session.add(req)
        await session.commit()

    return {"status": "pending", "message": "Live trading request submitted. Awaiting admin approval."}


# ── Helpers ──────────────────────────────────────────────────

def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        role=user.role.name if user.role else "viewer",
        trading_mode=user.trading_mode,
        is_active=user.is_active,
        approved_for_live=user.approved_for_live,
        max_risk_per_trade_pct=user.max_risk_per_trade_pct,
        max_portfolio_risk_pct=user.max_portfolio_risk_pct,
        min_signal_score=user.min_signal_score,
        paper_starting_capital=user.paper_starting_capital,
        created_at=user.created_at.isoformat() if user.created_at else None,
    )
