"""Configuration and portfolio risk tracking models."""

from datetime import datetime, date
from sqlalchemy import String, Integer, Float, DateTime, Date, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ConfigEntry(Base):
    __tablename__ = "config"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text)  # JSON value
    category: Mapped[str] = mapped_column(String(20))  # INDICATOR, RISK, BROKER, ALERT, SCANNER
    description: Mapped[str] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PortfolioRisk(Base):
    __tablename__ = "portfolio_risk"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    month_start_equity: Mapped[float] = mapped_column(Float)
    current_equity: Mapped[float] = mapped_column(Float)
    total_open_risk: Mapped[float] = mapped_column(Float, default=0.0)
    month_realized_losses: Mapped[float] = mapped_column(Float, default=0.0)
    total_risk_percent: Mapped[float] = mapped_column(Float, default=0.0)
    is_halted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
