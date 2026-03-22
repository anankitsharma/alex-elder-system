"""User, role, broker credentials, and notification models for multi-user support."""

from datetime import datetime
from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, ForeignKey, Text, Table, Column,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ── Junction table: role ↔ permission ─────────────────────────

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
    extend_existing=True,
)


# ── Roles & Permissions ──────────────────────────────────────

class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    permissions = relationship("Permission", secondary=role_permissions, back_populates="roles")


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(50))  # trading, risk, admin, data

    roles = relationship("Role", secondary=role_permissions, back_populates="permissions")


# ── User ─────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Role
    role_id: Mapped[int] = mapped_column(Integer, ForeignKey("roles.id"), default=3)  # Default: trader
    role = relationship("Role", lazy="joined")

    # Per-user trading settings
    trading_mode: Mapped[str] = mapped_column(String(10), default="PAPER")
    approved_for_live: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    # Per-user risk settings (override system defaults)
    max_risk_per_trade_pct: Mapped[float] = mapped_column(Float, default=2.0)
    max_portfolio_risk_pct: Mapped[float] = mapped_column(Float, default=6.0)
    min_signal_score: Mapped[int] = mapped_column(Integer, default=65)
    paper_starting_capital: Mapped[float] = mapped_column(Float, default=100000.0)

    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Broker Credentials (encrypted) ──────────────────────────

class UserBrokerCredentials(Base):
    __tablename__ = "user_broker_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    exchange: Mapped[str] = mapped_column(String(20), default="ANGEL_ONE")

    encrypted_api_key: Mapped[str] = mapped_column(Text, default="")
    encrypted_secret_key: Mapped[str] = mapped_column(Text, default="")
    encrypted_client_code: Mapped[str] = mapped_column(Text, default="")
    encrypted_password: Mapped[str] = mapped_column(Text, default="")
    encrypted_totp_secret: Mapped[str] = mapped_column(Text, default="")
    encrypted_hist_api_key: Mapped[str] = mapped_column(Text, default="")
    encrypted_hist_secret: Mapped[str] = mapped_column(Text, default="")
    encrypted_feed_api_key: Mapped[str] = mapped_column(Text, default="")
    encrypted_feed_secret: Mapped[str] = mapped_column(Text, default="")

    is_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    last_validated_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ── Notification Preferences ─────────────────────────────────

class UserNotificationConfig(Base):
    __tablename__ = "user_notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), unique=True)

    telegram_chat_id: Mapped[str] = mapped_column(String(50), default="")
    discord_webhook_url: Mapped[str] = mapped_column(Text, default="")

    min_priority: Mapped[int] = mapped_column(Integer, default=1)  # 1=LOW..4=CRITICAL
    quiet_hours_start: Mapped[str] = mapped_column(String(5), default="")
    quiet_hours_end: Mapped[str] = mapped_column(String(5), default="")
    alerts_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


# ── Access Requests ──────────────────────────────────────────

class AccessRequest(Base):
    __tablename__ = "access_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    request_type: Mapped[str] = mapped_column(String(50))  # live_trading, risk_override
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    reason: Mapped[str] = mapped_column(Text, default="")
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


# ── Per-Asset Settings ───────────────────────────────────────

class UserAssetSettings(Base):
    """Per-user, per-asset trading mode and preferences.

    Controls whether each specific asset trades in PAPER or LIVE mode
    independently. A user approved for LIVE can still keep some assets
    in PAPER while others trade real money.
    """
    __tablename__ = "user_asset_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(50), index=True)
    exchange: Mapped[str] = mapped_column(String(20))

    # Per-asset trading mode — overrides user.trading_mode for this asset
    trading_mode: Mapped[str] = mapped_column(String(10), default="PAPER")  # PAPER or LIVE
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # Is pipeline tracking active?

    # Per-asset timeframe overrides (nullable = use asset-class defaults)
    # Format: "1w", "1d", "1h", "15m", "5m"
    screen1_timeframe: Mapped[str] = mapped_column(String(10), nullable=True)  # Tide (e.g., "1w")
    screen2_timeframe: Mapped[str] = mapped_column(String(10), nullable=True)  # Wave (e.g., "1d")
    screen3_timeframe: Mapped[str] = mapped_column(String(10), nullable=True)  # Entry (e.g., "1h")

    # Per-asset risk overrides (nullable = use user defaults)
    max_risk_pct_override: Mapped[float] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
