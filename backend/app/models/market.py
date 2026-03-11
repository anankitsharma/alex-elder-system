"""Market data models — instruments and OHLCV candles."""

from datetime import datetime
from sqlalchemy import String, Integer, Float, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(20), index=True)
    symbol: Mapped[str] = mapped_column(String(50), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    exchange: Mapped[str] = mapped_column(String(10))  # NSE, NFO, BSE, MCX
    segment: Mapped[str] = mapped_column(String(10), default="EQ")  # EQ, FUT, OPT, COM
    lot_size: Mapped[int] = mapped_column(Integer, default=1)
    tick_size: Mapped[float] = mapped_column(Float, default=0.05)
    expiry: Mapped[str] = mapped_column(String(20), nullable=True)
    strike: Mapped[float] = mapped_column(Float, nullable=True)
    option_type: Mapped[str] = mapped_column(String(5), nullable=True)  # CE/PE
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("instrument_id", "timeframe", "timestamp", name="uq_candle"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(Integer, index=True)
    timeframe: Mapped[str] = mapped_column(String(10))  # 1m, 5m, 15m, 1h, 1d, 1w
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer)
