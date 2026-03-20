"""Admin API — user management, access requests, role assignment."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import joinedload

from app.database import async_session
from app.middleware.auth import get_current_user, RequireRole, Role
from app.models.user import (
    User, Role as RoleModel, AccessRequest,
    UserNotificationConfig,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── Schemas ──────────────────────────────────────────────────

class CreateUserRequest(BaseModel):
    email: str
    username: str
    password: str
    full_name: str = ""
    role: str = "trader"  # super_admin, admin, trader, viewer


class UpdateUserRequest(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    max_risk_per_trade_pct: Optional[float] = None
    max_portfolio_risk_pct: Optional[float] = None
    min_signal_score: Optional[int] = None
    paper_starting_capital: Optional[float] = None


class ReviewRequest(BaseModel):
    reason: str = ""


class UserListItem(BaseModel):
    id: int
    email: str
    username: str
    full_name: str
    role: str
    trading_mode: str
    is_active: bool
    approved_for_live: bool
    created_at: Optional[str] = None


# ── User Management (Super Admin) ───────────────────────────

@router.get("/users", dependencies=[Depends(RequireRole(Role.ADMIN))])
async def list_users(user: User = Depends(get_current_user)):
    """List all users. Admin+ only."""
    async with async_session() as session:
        result = await session.execute(
            select(User).options(joinedload(User.role)).order_by(User.id)
        )
        users = result.scalars().unique().all()
    return [
        UserListItem(
            id=u.id, email=u.email, username=u.username,
            full_name=u.full_name,
            role=u.role.name if u.role else "viewer",
            trading_mode=u.trading_mode,
            is_active=u.is_active,
            approved_for_live=u.approved_for_live,
            created_at=u.created_at.isoformat() if u.created_at else None,
        )
        for u in users
    ]


@router.post("/users", dependencies=[Depends(RequireRole(Role.SUPER_ADMIN))])
async def create_user(req: CreateUserRequest, admin: User = Depends(get_current_user)):
    """Create a new user. Super Admin only."""
    from app.middleware.auth import hash_password

    async with async_session() as session:
        # Check duplicate
        existing = await session.execute(
            select(User).where((User.email == req.email) | (User.username == req.username))
        )
        if existing.scalar_one_or_none():
            raise HTTPException(400, "Email or username already exists")

        # Resolve role
        role_result = await session.execute(
            select(RoleModel).where(RoleModel.name == req.role)
        )
        role = role_result.scalar_one_or_none()
        if not role:
            raise HTTPException(400, f"Role '{req.role}' not found")

        user = User(
            email=req.email,
            username=req.username,
            hashed_password=hash_password(req.password),
            full_name=req.full_name,
            role_id=role.id,
            trading_mode="PAPER",
            created_by=admin.id,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    return {"id": user.id, "username": user.username, "role": req.role}


@router.put("/users/{user_id}", dependencies=[Depends(RequireRole(Role.SUPER_ADMIN))])
async def update_user(user_id: int, req: UpdateUserRequest, admin: User = Depends(get_current_user)):
    """Update user role, status, or risk settings. Super Admin only."""
    async with async_session() as session:
        result = await session.execute(
            select(User).options(joinedload(User.role)).where(User.id == user_id)
        )
        target = result.scalar_one_or_none()
        if not target:
            raise HTTPException(404, "User not found")

        if req.role is not None:
            role_result = await session.execute(
                select(RoleModel).where(RoleModel.name == req.role)
            )
            role = role_result.scalar_one_or_none()
            if not role:
                raise HTTPException(400, f"Role '{req.role}' not found")
            target.role_id = role.id

        if req.is_active is not None:
            target.is_active = req.is_active
        if req.max_risk_per_trade_pct is not None:
            target.max_risk_per_trade_pct = req.max_risk_per_trade_pct
        if req.max_portfolio_risk_pct is not None:
            target.max_portfolio_risk_pct = req.max_portfolio_risk_pct
        if req.min_signal_score is not None:
            target.min_signal_score = req.min_signal_score
        if req.paper_starting_capital is not None:
            target.paper_starting_capital = req.paper_starting_capital

        target.updated_at = datetime.utcnow()
        await session.commit()

    return {"status": "updated", "user_id": user_id}


# ── Live Trading Approval ───────────────────────────────────

@router.get("/access-requests", dependencies=[Depends(RequireRole(Role.SUPER_ADMIN))])
async def list_access_requests():
    """List pending access requests."""
    async with async_session() as session:
        result = await session.execute(
            select(AccessRequest)
            .where(AccessRequest.status == "PENDING")
            .order_by(AccessRequest.requested_at.desc())
        )
        requests = result.scalars().all()

    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "request_type": r.request_type,
            "status": r.status,
            "requested_at": r.requested_at.isoformat() if r.requested_at else None,
        }
        for r in requests
    ]


@router.post("/approve-live/{user_id}", dependencies=[Depends(RequireRole(Role.SUPER_ADMIN))])
async def approve_live(user_id: int, body: ReviewRequest = None, admin: User = Depends(get_current_user)):
    """Approve a user for LIVE trading."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        target = result.scalar_one_or_none()
        if not target:
            raise HTTPException(404, "User not found")

        target.approved_for_live = True
        target.trading_mode = "LIVE"
        target.approved_by = admin.id
        target.approved_at = datetime.utcnow()

        # Update pending access request
        req_result = await session.execute(
            select(AccessRequest).where(
                AccessRequest.user_id == user_id,
                AccessRequest.request_type == "live_trading",
                AccessRequest.status == "PENDING",
            )
        )
        access_req = req_result.scalar_one_or_none()
        if access_req:
            access_req.status = "APPROVED"
            access_req.reviewed_by = admin.id
            access_req.reviewed_at = datetime.utcnow()
            access_req.reason = body.reason if body else "Approved"

        await session.commit()

    return {"status": "approved", "user_id": user_id, "trading_mode": "LIVE"}


@router.post("/reject-live/{user_id}", dependencies=[Depends(RequireRole(Role.SUPER_ADMIN))])
async def reject_live(user_id: int, body: ReviewRequest, admin: User = Depends(get_current_user)):
    """Reject a user's LIVE trading request."""
    async with async_session() as session:
        req_result = await session.execute(
            select(AccessRequest).where(
                AccessRequest.user_id == user_id,
                AccessRequest.request_type == "live_trading",
                AccessRequest.status == "PENDING",
            )
        )
        access_req = req_result.scalar_one_or_none()
        if not access_req:
            raise HTTPException(404, "No pending request found")

        access_req.status = "REJECTED"
        access_req.reviewed_by = admin.id
        access_req.reviewed_at = datetime.utcnow()
        access_req.reason = body.reason

        await session.commit()

    return {"status": "rejected", "user_id": user_id, "reason": body.reason}


# ── System Stats ─────────────────────────────────────────────

@router.get("/stats", dependencies=[Depends(RequireRole(Role.ADMIN))])
async def system_stats():
    """System-wide statistics. Admin+ only."""
    from app.models.trade import Order, Position, Trade

    async with async_session() as session:
        user_count = await session.execute(select(func.count(User.id)))
        active_users = await session.execute(
            select(func.count(User.id)).where(User.is_active == True)
        )
        open_positions = await session.execute(
            select(func.count(Position.id)).where(Position.status == "OPEN")
        )
        total_trades = await session.execute(select(func.count(Trade.id)))

    return {
        "total_users": user_count.scalar(),
        "active_users": active_users.scalar(),
        "open_positions": open_positions.scalar(),
        "total_trades": total_trades.scalar(),
    }
