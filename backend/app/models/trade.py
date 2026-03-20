"""Order, Position, and Trade journal models."""

from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, Float, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    signal_id: Mapped[int] = mapped_column(Integer, nullable=True)
    instrument_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(50))
    order_id: Mapped[str] = mapped_column(String(50), nullable=True)  # Angel One order ID
    direction: Mapped[str] = mapped_column(String(10))  # BUY, SELL
    order_type: Mapped[str] = mapped_column(String(10))  # MARKET, LIMIT, SL, SL-M
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float, nullable=True)
    trigger_price: Mapped[float] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    mode: Mapped[str] = mapped_column(String(10))  # PAPER, LIVE
    filled_price: Mapped[float] = mapped_column(Float, nullable=True)
    filled_quantity: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    instrument_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(50))
    direction: Mapped[str] = mapped_column(String(10))  # LONG, SHORT
    entry_price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer)
    stop_price: Mapped[float] = mapped_column(Float, nullable=True)
    target_price: Mapped[float] = mapped_column(Float, nullable=True)
    current_price: Mapped[float] = mapped_column(Float, nullable=True)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    risk_amount: Mapped[float] = mapped_column(Float, default=0.0)
    risk_percent: Mapped[float] = mapped_column(Float, default=0.0)
    mode: Mapped[str] = mapped_column(String(10))  # PAPER, LIVE
    status: Mapped[str] = mapped_column(String(10), default="OPEN")
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    closed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    position_id: Mapped[int] = mapped_column(Integer, nullable=True)
    instrument_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(50))
    direction: Mapped[str] = mapped_column(String(10))
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer)
    pnl: Mapped[float] = mapped_column(Float)
    pnl_percent: Mapped[float] = mapped_column(Float, nullable=True)
    channel_width: Mapped[float] = mapped_column(Float, nullable=True)
    grade: Mapped[str] = mapped_column(String(5), nullable=True)  # A, B, C, D
    grade_percent: Mapped[float] = mapped_column(Float, nullable=True)
    strategy: Mapped[str] = mapped_column(String(30), nullable=True)
    signal_score: Mapped[int] = mapped_column(Integer, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(String(10))
    entry_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    exit_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
