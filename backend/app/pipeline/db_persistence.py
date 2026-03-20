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
from app.models.market import Instrument, Candle, RolloverHistory
from app.models.trade import Order, Position, Trade
from app.models.signal import Signal
from app.models.config import PortfolioRisk


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
    contract_token: str = "",
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
            contract_token=contract_token or None,
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
        user_id=signal_data.get("user_id"),
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
        user_id=order_data.get("user_id"),
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
        user_id=position_data.get("user_id"),
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
    """Close a position and create a trade record atomically.

    Uses a single transaction: position update + trade insert commit together.
    If anything fails, both are rolled back. Also uses optimistic check:
    only updates if status is still OPEN (prevents double-close race).
    """
    try:
        stmt = select(Position).where(
            and_(Position.id == position_id, Position.status == "OPEN")
        )
        result = await session.execute(stmt)
        pos = result.scalar_one_or_none()

        if pos is None:
            return None  # Already closed or doesn't exist

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
            user_id=pos.user_id,
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

        # Atomic commit: position update + trade insert together
        await session.commit()
        await session.refresh(trade)

        logger.info("Closed position {} → trade {} PnL={:.2f}", position_id, trade.id, pnl)
        return trade

    except Exception as e:
        await session.rollback()
        logger.error("Failed to close position {}: {}", position_id, e)
        raise


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


async def load_open_positions_by_symbol(
    session: AsyncSession, symbol: str,
) -> list[Position]:
    """Load open positions for a specific symbol."""
    stmt = select(Position).where(
        and_(Position.symbol == symbol, Position.status == "OPEN")
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_position_stop(
    session: AsyncSession, position_id: int, new_stop: float, current_price: float,
) -> None:
    """Update trailing stop on a position (only tightens, never widens)."""
    stmt = select(Position).where(Position.id == position_id)
    result = await session.execute(stmt)
    pos = result.scalar_one_or_none()
    if pos and pos.status == "OPEN":
        # Elder's rule: stop only tightens, never widens
        if pos.direction == "LONG" and new_stop > (pos.stop_price or 0):
            pos.stop_price = new_stop
        elif pos.direction == "SHORT" and new_stop < (pos.stop_price or float("inf")):
            pos.stop_price = new_stop
        pos.current_price = current_price
        # Update unrealized P&L
        if pos.direction == "LONG":
            pos.unrealized_pnl = (current_price - pos.entry_price) * pos.quantity
        else:
            pos.unrealized_pnl = (pos.entry_price - current_price) * pos.quantity
        await session.commit()


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


# ── Asset Detail Queries ─────────────────────────────────────

async def load_orders_by_symbol(
    session: AsyncSession, symbol: str, limit: int = 50,
) -> list[dict]:
    """Load orders for a symbol, newest first."""
    stmt = (
        select(Order)
        .where(Order.symbol == symbol)
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [{
        "id": r.id,
        "order_id": r.order_id,
        "symbol": r.symbol,
        "direction": r.direction,
        "order_type": r.order_type,
        "quantity": r.quantity,
        "price": r.price,
        "filled_price": r.filled_price,
        "filled_quantity": r.filled_quantity,
        "status": r.status,
        "mode": r.mode,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in result.scalars().all()]


async def load_pending_orders(session: AsyncSession) -> list[Order]:
    """Load PENDING orders (for live fill polling). Limited to 100 to prevent OOM."""
    stmt = (
        select(Order)
        .where(Order.status == "PENDING")
        .order_by(Order.created_at.desc())
        .limit(100)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# Valid order status transitions (FSM)
_ORDER_TRANSITIONS = {
    "PENDING": {"COMPLETE", "REJECTED", "CANCELLED"},
    "COMPLETE": set(),       # Terminal state
    "REJECTED": set(),       # Terminal state
    "CANCELLED": set(),      # Terminal state
}


async def update_order_fill(
    session: AsyncSession,
    order_id: int,
    filled_price: float = None,
    filled_quantity: int = None,
    status: str = "COMPLETE",
) -> None:
    """Update an order with fill information from broker.

    Validates status transitions and filled_quantity <= order.quantity.
    """
    stmt = select(Order).where(Order.id == order_id)
    result = await session.execute(stmt)
    order = result.scalar_one_or_none()
    if not order:
        return

    # Validate status transition
    allowed = _ORDER_TRANSITIONS.get(order.status, set())
    if status != order.status and status not in allowed:
        logger.warning(
            "Invalid order status transition: {} → {} (order {})",
            order.status, status, order_id,
        )
        return

    # Validate filled quantity doesn't exceed order quantity
    if filled_quantity is not None and order.quantity:
        if filled_quantity > order.quantity:
            logger.warning(
                "Filled quantity {} exceeds order quantity {} (order {})",
                filled_quantity, order.quantity, order_id,
            )
            filled_quantity = order.quantity

    order.status = status
    if filled_price is not None:
        order.filled_price = filled_price
    if filled_quantity is not None:
        order.filled_quantity = filled_quantity
    await session.commit()


async def load_positions_by_symbol(
    session: AsyncSession, symbol: str, limit: int = 50,
) -> list[dict]:
    """Load positions for a symbol, newest first."""
    stmt = (
        select(Position)
        .where(Position.symbol == symbol)
        .order_by(Position.opened_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [{
        "id": r.id,
        "symbol": r.symbol,
        "direction": r.direction,
        "entry_price": r.entry_price,
        "quantity": r.quantity,
        "stop_price": r.stop_price,
        "current_price": r.current_price,
        "unrealized_pnl": r.unrealized_pnl,
        "risk_amount": r.risk_amount,
        "status": r.status,
        "mode": r.mode,
        "created_at": r.opened_at.isoformat() if r.opened_at else None,
        "closed_at": r.closed_at.isoformat() if r.closed_at else None,
    } for r in result.scalars().all()]


# ── Rollover History ─────────────────────────────────────────

async def save_rollover(
    session: AsyncSession,
    symbol: str,
    exchange: str,
    old_token: str,
    old_contract: str,
    new_token: str,
    new_contract: str,
    old_expiry: str = "",
    new_expiry: str = "",
    positions_closed: int = 0,
) -> RolloverHistory:
    """Record a contract rollover event."""
    entry = RolloverHistory(
        symbol=symbol,
        exchange=exchange,
        old_token=old_token,
        old_contract=old_contract,
        new_token=new_token,
        new_contract=new_contract,
        old_expiry=old_expiry,
        new_expiry=new_expiry,
        positions_closed=positions_closed,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    logger.info("Rollover recorded: {} {} -> {} ({})",
                symbol, old_contract, new_contract, entry.rolled_at)
    return entry


async def load_rollover_history(
    session: AsyncSession, symbol: str = "", limit: int = 50,
) -> list[dict]:
    """Load rollover history, newest first."""
    stmt = select(RolloverHistory).order_by(RolloverHistory.rolled_at.desc()).limit(limit)
    if symbol:
        stmt = stmt.where(RolloverHistory.symbol == symbol)
    result = await session.execute(stmt)
    return [{
        "id": r.id,
        "symbol": r.symbol,
        "exchange": r.exchange,
        "old_token": r.old_token,
        "old_contract": r.old_contract,
        "new_token": r.new_token,
        "new_contract": r.new_contract,
        "old_expiry": r.old_expiry,
        "new_expiry": r.new_expiry,
        "positions_closed": r.positions_closed,
        "rolled_at": r.rolled_at.isoformat() if r.rolled_at else None,
    } for r in result.scalars().all()]


# ── Portfolio Equity Tracking ────────────────────────────────

async def get_or_create_portfolio_risk(
    session: AsyncSession,
    default_equity: float = 100000.0,
    user_id: Optional[int] = None,
) -> PortfolioRisk:
    """Get today's portfolio risk record, or create one.

    On the 1st of a new month (or first ever run), sets month_start_equity
    from the previous record's current_equity. Falls back to default_equity.
    """
    from datetime import date as _date
    today = _date.today()
    month_str = today.strftime("%Y-%m")

    # Try today's record (filtered by user_id if provided)
    stmt = select(PortfolioRisk).where(PortfolioRisk.date == today)
    if user_id is not None:
        stmt = stmt.where(PortfolioRisk.user_id == user_id)
    result = await session.execute(stmt)
    record = result.scalar_one_or_none()
    if record:
        return record

    # No record for today — find the most recent one
    prev_stmt = (
        select(PortfolioRisk)
        .order_by(PortfolioRisk.date.desc())
        .limit(1)
    )
    if user_id is not None:
        prev_stmt = prev_stmt.where(PortfolioRisk.user_id == user_id)
    prev_result = await session.execute(prev_stmt)
    prev = prev_result.scalar_one_or_none()

    if prev:
        prev_month = prev.date.strftime("%Y-%m")
        if prev_month == month_str:
            # Same month — carry forward month_start_equity
            month_start = prev.month_start_equity
        else:
            # New month — use previous record's current equity as new month start
            month_start = prev.current_equity
        current = prev.current_equity
    else:
        # First ever record
        month_start = default_equity
        current = default_equity

    record = PortfolioRisk(
        user_id=user_id,
        date=today,
        month_start_equity=month_start,
        current_equity=current,
        total_open_risk=0.0,
        month_realized_losses=0.0,
        total_risk_percent=0.0,
        is_halted=False,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    logger.info(
        "Portfolio risk record created: date={} month_start={:.2f} current={:.2f}",
        today, month_start, current,
    )
    return record


async def update_portfolio_equity(
    session: AsyncSession,
    realized_pnl: float,
    user_id: Optional[int] = None,
) -> PortfolioRisk:
    """Update current equity after a trade closes.

    Args:
        realized_pnl: Positive = profit, negative = loss.
        user_id: Optional user ID for multi-user filtering.
    """
    from app.config import settings
    record = await get_or_create_portfolio_risk(
        session, default_equity=settings.paper_starting_capital, user_id=user_id,
    )
    record.current_equity += realized_pnl
    if realized_pnl < 0:
        record.month_realized_losses += abs(realized_pnl)
    record.updated_at = datetime.utcnow()
    await session.commit()
    return record


async def get_current_equity(
    session: AsyncSession,
    user_id: Optional[int] = None,
) -> float:
    """Get current account equity from latest portfolio risk record."""
    from app.config import settings
    record = await get_or_create_portfolio_risk(
        session, default_equity=settings.paper_starting_capital, user_id=user_id,
    )
    return record.current_equity


async def get_month_start_equity(
    session: AsyncSession,
    user_id: Optional[int] = None,
) -> float:
    """Get month-start equity for circuit breaker."""
    from app.config import settings
    record = await get_or_create_portfolio_risk(
        session, default_equity=settings.paper_starting_capital, user_id=user_id,
    )
    return record.month_start_equity


async def load_continuous_candles(
    session: AsyncSession,
    symbol: str,
    exchange: str,
    timeframe: str,
    days: int = 365,
) -> pd.DataFrame:
    """Load continuous candle data across contract boundaries.

    Stitches candles from multiple contracts for the same symbol by
    querying all instrument_ids that match the symbol+exchange, then
    merging by timestamp (latest contract's data wins on overlap).
    """
    # Find all instrument IDs for this symbol
    inst_stmt = select(Instrument.id).where(
        and_(Instrument.symbol == symbol, Instrument.exchange == exchange)
    )
    inst_result = await session.execute(inst_stmt)
    inst_ids = [r[0] for r in inst_result.all()]

    if not inst_ids:
        return pd.DataFrame()

    since = datetime.now() - __import__("datetime").timedelta(days=days)

    # Load candles from all contracts
    stmt = (
        select(Candle)
        .where(
            and_(
                Candle.instrument_id.in_(inst_ids),
                Candle.timeframe == timeframe,
                Candle.timestamp >= since,
            )
        )
        .order_by(Candle.timestamp)
    )
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

    df = pd.DataFrame(data)

    # Remove duplicates (same timestamp from different contracts — keep last)
    df = df.drop_duplicates(subset=["timestamp"], keep="last")
    df = df.sort_values("timestamp").reset_index(drop=True)

    return df
