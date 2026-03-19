"""DB persistence layer for the trading pipeline.

Async CRUD operations using existing SQLAlchemy models.
"""

import json
from datetime import datetime
from typing import Optional

import pandas as pd
from loguru import logger
from sqlalchemy import select, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.market import Instrument, Candle
from app.models.trade import Order, Position, Trade
from app.models.signal import Signal


# ── Instruments ──────────────────────────────────────────────

async def get_or_create_instrument(
    session: AsyncSession,
    symbol: str,
    exchange: str,
    token: str,
    name: str = "",
) -> Instrument:
    """Get existing instrument or create a new one."""
    stmt = select(Instrument).where(
        and_(Instrument.symbol == symbol, Instrument.exchange == exchange)
    )
    result = await session.execute(stmt)
    inst = result.scalar_one_or_none()

    if inst is None:
        inst = Instrument(
            token=token,
            symbol=symbol,
            name=name,
            exchange=exchange,
            segment="EQ",
            updated_at=datetime.utcnow(),
        )
        session.add(inst)
        await session.commit()
        await session.refresh(inst)
        logger.info("Created instrument: {} ({}) id={}", symbol, exchange, inst.id)

    return inst


# ── Candles ──────────────────────────────────────────────────

async def save_candles(
    session: AsyncSession,
    instrument_id: int,
    timeframe: str,
    candles: list[dict],
) -> int:
    """Save candles to DB (bulk insert, skip existing)."""
    if not candles:
        return 0

    # Fetch existing timestamps in one query for dedup
    stmt = select(Candle.timestamp).where(
        and_(
            Candle.instrument_id == instrument_id,
            Candle.timeframe == timeframe,
        )
    )
    result = await session.execute(stmt)
    existing_ts = {r[0] for r in result.all()}

    new_candles = []
    for c in candles:
        ts = c.get("timestamp") or c.get("datetime")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                continue
        if hasattr(ts, 'tzinfo') and ts.tzinfo is not None:
            ts = ts.replace(tzinfo=None)

        if ts in existing_ts:
            continue

        new_candles.append(Candle(
            instrument_id=instrument_id,
            timeframe=timeframe,
            timestamp=ts,
            open=float(c["open"]),
            high=float(c["high"]),
            low=float(c["low"]),
            close=float(c["close"]),
            volume=int(c.get("volume", 0)),
        ))

    if new_candles:
        session.add_all(new_candles)
        await session.commit()

    return len(new_candles)


async def load_candles(
    session: AsyncSession,
    instrument_id: int,
    timeframe: str,
    since: Optional[datetime] = None,
) -> pd.DataFrame:
    """Load candles from DB as DataFrame."""
    stmt = select(Candle).where(
        and_(
            Candle.instrument_id == instrument_id,
            Candle.timeframe == timeframe,
        )
    )
    if since:
        stmt = stmt.where(Candle.timestamp >= since)
    stmt = stmt.order_by(Candle.timestamp)

    result = await session.execute(stmt)
    rows = result.scalars().all()

    if not rows:
        return pd.DataFrame()

    data = [{
        "timestamp": r.timestamp,
        "open": r.open,
        "high": r.high,
        "low": r.low,
        "close": r.close,
        "volume": r.volume,
    } for r in rows]

    return pd.DataFrame(data)


async def load_candles_since(
    session: AsyncSession,
    instrument_id: int,
    timeframe: str,
    since_dt: datetime,
) -> list[dict]:
    """Load candles since a timestamp as list of dicts (for backfill)."""
    stmt = (
        select(Candle)
        .where(
            and_(
                Candle.instrument_id == instrument_id,
                Candle.timeframe == timeframe,
                Candle.timestamp > since_dt,
            )
        )
        .order_by(Candle.timestamp)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    return [{
        "timestamp": r.timestamp.isoformat() if hasattr(r.timestamp, 'isoformat') else str(r.timestamp),
        "open": r.open,
        "high": r.high,
        "low": r.low,
        "close": r.close,
        "volume": r.volume,
    } for r in rows]


async def detect_candle_gaps(
    session: AsyncSession,
    instrument_id: int,
    timeframe: str,
) -> list[tuple[datetime, datetime]]:
    """Detect gaps in candle data. Returns list of (gap_start, gap_end) tuples."""
    stmt = (
        select(Candle.timestamp)
        .where(
            and_(
                Candle.instrument_id == instrument_id,
                Candle.timeframe == timeframe,
            )
        )
        .order_by(Candle.timestamp)
    )
    result = await session.execute(stmt)
    timestamps = [r[0] for r in result.all()]

    if len(timestamps) < 2:
        return []

    # Expected gap between bars
    if timeframe == "1d":
        max_gap = pd.Timedelta(days=4)  # Account for weekends
    elif timeframe == "1w":
        max_gap = pd.Timedelta(days=10)
    elif timeframe == "1h":
        max_gap = pd.Timedelta(hours=2)
    else:
        minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30}.get(timeframe, 60)
        max_gap = pd.Timedelta(minutes=minutes * 3)

    gaps = []
    for i in range(1, len(timestamps)):
        delta = timestamps[i] - timestamps[i - 1]
        if delta > max_gap:
            gaps.append((timestamps[i - 1], timestamps[i]))

    return gaps


# ── Signals ──────────────────────────────────────────────────

async def save_signal(session: AsyncSession, signal_data: dict) -> Signal:
    """Persist a trading signal."""
    confirmations = signal_data.get("confirmations", [])
    if isinstance(confirmations, list):
        confirmations = json.dumps(confirmations)

    sig = Signal(
        instrument_id=signal_data["instrument_id"],
        symbol=signal_data["symbol"],
        timestamp=signal_data.get("timestamp", datetime.utcnow()),
        direction=signal_data["direction"],
        score=signal_data.get("score", 0),
        strategy=signal_data.get("strategy", "TRIPLE_SCREEN"),
        confirmations=confirmations,
        entry_price=signal_data.get("entry_price"),
        stop_price=signal_data.get("stop_price"),
        target_price=signal_data.get("target_price"),
        status=signal_data.get("status", "PENDING"),
    )
    session.add(sig)
    await session.commit()
    await session.refresh(sig)
    logger.info("Saved signal id={} {} {} score={}",
                sig.id, sig.symbol, sig.direction, sig.score)
    return sig


async def load_recent_signals(
    session: AsyncSession,
    instrument_id: Optional[int] = None,
    limit: int = 20,
) -> list[dict]:
    """Load recent signals, newest first."""
    stmt = select(Signal).order_by(Signal.created_at.desc()).limit(limit)
    if instrument_id is not None:
        stmt = stmt.where(Signal.instrument_id == instrument_id)

    result = await session.execute(stmt)
    rows = result.scalars().all()

    return [{
        "id": r.id,
        "symbol": r.symbol,
        "direction": r.direction,
        "score": r.score,
        "strategy": r.strategy,
        "entry_price": r.entry_price,
        "stop_price": r.stop_price,
        "target_price": r.target_price,
        "status": r.status,
        "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]


# ── Orders ───────────────────────────────────────────────────

async def save_order(session: AsyncSession, order_data: dict) -> Order:
    """Persist an order to DB."""
    order = Order(
        signal_id=order_data.get("signal_id"),
        instrument_id=order_data["instrument_id"],
        symbol=order_data["symbol"],
        order_id=order_data.get("order_id"),
        direction=order_data["direction"],
        order_type=order_data.get("order_type", "MARKET"),
        quantity=order_data["quantity"],
        price=order_data.get("price"),
        trigger_price=order_data.get("trigger_price"),
        status=order_data.get("status", "PENDING"),
        mode=order_data.get("mode", "PAPER"),
        filled_price=order_data.get("filled_price"),
        filled_quantity=order_data.get("filled_quantity"),
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)
    return order


# ── Positions ────────────────────────────────────────────────

async def save_position(session: AsyncSession, position_data: dict) -> Position:
    """Persist a position to DB."""
    pos = Position(
        instrument_id=position_data["instrument_id"],
        symbol=position_data["symbol"],
        direction=position_data["direction"],
        entry_price=position_data["entry_price"],
        quantity=position_data["quantity"],
        stop_price=position_data.get("stop_price"),
        target_price=position_data.get("target_price"),
        current_price=position_data.get("current_price"),
        unrealized_pnl=position_data.get("unrealized_pnl", 0.0),
        risk_amount=position_data.get("risk_amount", 0.0),
        risk_percent=position_data.get("risk_percent", 0.0),
        mode=position_data.get("mode", "PAPER"),
        status="OPEN",
    )
    session.add(pos)
    await session.commit()
    await session.refresh(pos)
    return pos


async def close_position(
    session: AsyncSession,
    position_id: int,
    exit_price: float,
    exit_time: Optional[datetime] = None,
) -> Optional[Trade]:
    """Close a position and create a trade record."""
    stmt = select(Position).where(Position.id == position_id)
    result = await session.execute(stmt)
    pos = result.scalar_one_or_none()

    if pos is None or pos.status == "CLOSED":
        return None

    pos.status = "CLOSED"
    pos.closed_at = exit_time or datetime.utcnow()
    pos.current_price = exit_price

    # Calculate PnL
    if pos.direction == "LONG":
        pnl = (exit_price - pos.entry_price) * pos.quantity
    else:
        pnl = (pos.entry_price - exit_price) * pos.quantity

    pnl_pct = (pnl / (pos.entry_price * pos.quantity)) * 100.0 if pos.entry_price > 0 else 0.0

    trade = Trade(
        position_id=pos.id,
        instrument_id=pos.instrument_id,
        symbol=pos.symbol,
        direction=pos.direction,
        entry_price=pos.entry_price,
        exit_price=exit_price,
        quantity=pos.quantity,
        pnl=round(pnl, 2),
        pnl_percent=round(pnl_pct, 2),
        mode=pos.mode,
        entry_time=pos.opened_at,
        exit_time=pos.closed_at,
    )
    session.add(trade)
    await session.commit()
    await session.refresh(trade)

    logger.info("Closed position {} → trade {} PnL={:.2f}", position_id, trade.id, pnl)
    return trade


async def load_open_positions(
    session: AsyncSession,
    mode: Optional[str] = None,
) -> list[Position]:
    """Load all open positions."""
    stmt = select(Position).where(Position.status == "OPEN")
    if mode:
        stmt = stmt.where(Position.mode == mode)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def load_month_trades(
    session: AsyncSession,
    month: str,
) -> list[Trade]:
    """Load all trades for a given month (YYYY-MM format)."""
    year, mon = int(month[:4]), int(month[5:7])
    start = datetime(year, mon, 1)
    if mon == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, mon + 1, 1)

    stmt = select(Trade).where(
        and_(Trade.created_at >= start, Trade.created_at < end)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
