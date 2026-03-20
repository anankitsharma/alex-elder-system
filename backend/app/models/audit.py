"""Audit log model for tracking all system mutations."""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, DateTime, Text, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True,
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True,
    )
    action: Mapped[str] = mapped_column(
        String(100), index=True,
    )  # 'order:create', 'auth:login', etc.
    category: Mapped[str] = mapped_column(
        String(50), index=True,
    )  # 'auth', 'trading', 'risk', 'admin'
    resource_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True,
    )
    resource_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
    )
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True,
    )
    user_agent: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True,
    )
    severity: Mapped[str] = mapped_column(
        String(10), default="INFO",
    )  # INFO, WARNING, CRITICAL
