"""Strategy & Risk API — Triple Screen analysis, position sizing, circuit breaker."""

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from loguru import logger

from app.config import settings

router = APIRouter(prefix="/api/strategy", tags=["strategy"])

# Singleton instances
_circuit_breaker = None
_position_sizer = None


def _get_circuit_breaker():
    global _circuit_breaker
    if _circuit_breaker is None:
        from app.risk.circuit_breaker import CircuitBreaker
        _circuit_breaker = CircuitBreaker({
            "max_portfolio_risk_pct": settings.max_portfolio_risk_pct,
        })
    return _circuit_breaker


def _get_position_sizer():
    global _position_sizer
    if _position_sizer is None:
        from app.risk.position_sizer import PositionSizer
        _position_sizer = PositionSizer({
            "max_risk_per_trade_pct": settings.max_risk_per_trade_pct,
        })
    return _position_sizer


# --- Models ---

class PositionSizeRequest(BaseModel):
    entry_price: float
    stop_price: float
    account_equity: float
    lot_size: int = 1
    max_risk_pct: Optional[float] = None


class CircuitBreakerLossRequest(BaseModel):
    loss_amount: float


class CircuitBreakerEquityRequest(BaseModel):
    equity: float


class TripleScreenRequest(BaseModel):
    # Explicit indicator values (original mode)
    macd_histogram_slope: Optional[float] = None
    screen1_impulse: str = "neutral"
    screen1_ema_trend: str = "UNKNOWN"
    force_index_2: Optional[float] = None
    elder_ray_bear: float = 0
    elder_ray_bull: float = 0
    elder_ray_bear_trend: str = "UNKNOWN"
    elder_ray_bull_trend: str = "UNKNOWN"
    screen2_impulse: str = "neutral"
    value_zone_position: Optional[float] = None
    last_high: Optional[float] = None
    last_low: Optional[float] = None
    safezone_long: Optional[float] = None
    safezone_short: Optional[float] = None
    # Raw data mode: send candles + indicators, backend extracts latest values
    candles: Optional[List[dict]] = None
    indicators: Optional[dict] = None


# --- Endpoints ---

@router.post("/position-size")
async def calculate_position_size(req: PositionSizeRequest):
    """Calculate position size using Elder's 2% Rule."""
    ps = _get_position_sizer()
    return ps.calculate_position_size(
        entry_price=req.entry_price,
        stop_price=req.stop_price,
        account_equity=req.account_equity,
        lot_size=req.lot_size,
        max_risk_pct=req.max_risk_pct,
    )


@router.get("/circuit-breaker")
async def get_circuit_breaker_status():
    """Get current 6% Rule circuit breaker status."""
    cb = _get_circuit_breaker()
    return cb.get_status()


@router.post("/circuit-breaker/set-equity")
async def set_month_start_equity(req: CircuitBreakerEquityRequest):
    """Set month-start equity for 6% Rule calculation."""
    cb = _get_circuit_breaker()
    cb.set_month_start_equity(req.equity)
    return {"status": "ok", "month_start_equity": req.equity}


@router.post("/circuit-breaker/record-loss")
async def record_loss(req: CircuitBreakerLossRequest):
    """Record a realized loss for 6% Rule tracking."""
    cb = _get_circuit_breaker()
    cb.record_loss(req.loss_amount)
    return cb.get_status()


@router.post("/circuit-breaker/halt")
async def force_halt():
    """Manually halt trading."""
    cb = _get_circuit_breaker()
    cb.force_halt("Manual halt via API")
    return cb.get_status()


@router.post("/circuit-breaker/reset")
async def reset_halt():
    """Reset circuit breaker halt."""
    cb = _get_circuit_breaker()
    cb.reset_halt()
    return cb.get_status()


try:
    from app.pipeline.utils import last_non_null as _last_non_null
    from app.pipeline.utils import slope_of_last as _slope_of_last
    from app.pipeline.utils import trend_of_last as _trend_of_last
except ImportError:
    from backend.app.pipeline.utils import last_non_null as _last_non_null
    from backend.app.pipeline.utils import slope_of_last as _slope_of_last
    from backend.app.pipeline.utils import trend_of_last as _trend_of_last


@router.post("/triple-screen")
async def analyze_triple_screen(req: TripleScreenRequest):
    """Run Triple Screen analysis with provided indicator data."""
    from app.strategy.triple_screen import TripleScreenAnalysis

    ts = TripleScreenAnalysis()

    # If raw candles + indicators provided, extract values automatically
    if req.candles and req.indicators:
        ind = req.indicators
        candles = req.candles

        macd_h = ind.get("macd_histogram", [])
        fi2 = ind.get("force_index_2", [])
        er_bull = ind.get("elder_ray_bull", [])
        er_bear = ind.get("elder_ray_bear", [])
        impulse = ind.get("impulse_signal", [])
        vz_fast = ind.get("value_zone_fast", [])
        vz_slow = ind.get("value_zone_slow", [])
        sz_long = ind.get("safezone_long", [])
        sz_short = ind.get("safezone_short", [])

        # Extract latest values
        last_impulse = _last_non_null(impulse, "neutral")
        last_close = candles[-1].get("close", 0) if candles else 0
        last_vz_fast = _last_non_null(vz_fast)
        last_vz_slow = _last_non_null(vz_slow)

        # Determine value zone position
        vz_position = None
        if last_vz_fast and last_vz_slow and last_close:
            if min(last_vz_fast, last_vz_slow) <= last_close <= max(last_vz_fast, last_vz_slow):
                vz_position = 0  # In zone
            elif last_close > max(last_vz_fast, last_vz_slow):
                vz_position = 1  # Above
            else:
                vz_position = -1  # Below

        screen1 = {
            "macd_histogram_slope": _slope_of_last(macd_h),
            "impulse_signal": last_impulse,
            "ema_trend": _trend_of_last(ind.get("ema13", [])),
        }
        screen2 = {
            "force_index_2": _last_non_null(fi2),
            "elder_ray_bear": _last_non_null(er_bear),
            "elder_ray_bull": _last_non_null(er_bull),
            "elder_ray_bear_trend": _trend_of_last(er_bear),
            "elder_ray_bull_trend": _trend_of_last(er_bull),
            "impulse_signal": last_impulse,
            "value_zone_position": vz_position,
        }
        screen3 = None
        if len(candles) >= 2:
            prev = candles[-2]
            screen3 = {
                "last_high": prev.get("high", 0),
                "last_low": prev.get("low", 0),
                "safezone_long": _last_non_null(sz_long),
                "safezone_short": _last_non_null(sz_short),
            }

        return ts.analyze(screen1, screen2, screen3)

    # Explicit values mode (original)
    screen1 = {
        "macd_histogram_slope": req.macd_histogram_slope or 0,
        "impulse_signal": req.screen1_impulse,
        "ema_trend": req.screen1_ema_trend,
    }
    screen2 = {
        "force_index_2": req.force_index_2 or 0,
        "elder_ray_bear": req.elder_ray_bear,
        "elder_ray_bull": req.elder_ray_bull,
        "elder_ray_bear_trend": req.elder_ray_bear_trend,
        "elder_ray_bull_trend": req.elder_ray_bull_trend,
        "impulse_signal": req.screen2_impulse,
        "value_zone_position": req.value_zone_position,
    }
    screen3 = None
    if req.last_high is not None and req.last_low is not None:
        screen3 = {
            "last_high": req.last_high,
            "last_low": req.last_low,
            "safezone_long": req.safezone_long or 0,
            "safezone_short": req.safezone_short or 0,
        }

    return ts.analyze(screen1, screen2, screen3)


@router.get("/screen-config")
async def get_screen_config(symbol: str = Query("RELIANCE"), exchange: str = Query("NSE")):
    """Get asset class, timeframe mapping, and indicator config for a symbol."""
    try:
        from app.indicators.timeframe_config import (
            get_asset_class, get_timeframe_for_screen,
            get_indicators_for_screen, ASSET_TIMEFRAME_MAP,
        )
    except ImportError:
        from backend.app.indicators.timeframe_config import (
            get_asset_class, get_timeframe_for_screen,
            get_indicators_for_screen, ASSET_TIMEFRAME_MAP,
        )

    asset_class = get_asset_class(symbol, exchange)
    return {
        "symbol": symbol,
        "exchange": exchange,
        "asset_class": asset_class,
        "screens": {
            "1": {
                "label": "Tide (Trend)",
                "timeframe": get_timeframe_for_screen(symbol, 1, exchange),
                "indicators": get_indicators_for_screen(1),
            },
            "2": {
                "label": "Wave (Oscillator)",
                "timeframe": get_timeframe_for_screen(symbol, 2, exchange),
                "indicators": get_indicators_for_screen(2),
            },
            "3": {
                "label": "Ripple (Entry)",
                "timeframe": get_timeframe_for_screen(symbol, 3, exchange),
                "indicators": get_indicators_for_screen(3),
            },
        },
        "all_timeframe_maps": ASSET_TIMEFRAME_MAP,
    }


@router.get("/risk-summary")
async def get_risk_summary():
    """Get complete risk management summary."""
    cb = _get_circuit_breaker()
    status = cb.get_status()

    return {
        "two_percent_rule": {
            "max_risk_per_trade_pct": settings.max_risk_per_trade_pct,
            "description": "Never risk more than 2% of equity on a single trade",
        },
        "six_percent_rule": status,
        "trading_mode": settings.trading_mode,
        "min_signal_score": settings.min_signal_score,
    }


# ── Kill Switch Endpoints ──────────────────────────────────

@router.post("/pipeline/kill-switch")
async def activate_kill_switch(reason: str = Query("Manual activation")):
    """Emergency halt — stop all order flow across all asset sessions."""
    from app.pipeline import pipeline_manager
    await pipeline_manager.activate_kill_switch(reason)
    return {"status": "activated", "reason": reason}


@router.post("/pipeline/kill-switch/deactivate")
async def deactivate_kill_switch():
    """Deactivate kill switch — resume normal trading operation."""
    from app.pipeline import pipeline_manager
    pipeline_manager.deactivate_kill_switch()
    return {"status": "deactivated"}


@router.get("/pipeline/kill-switch")
async def get_kill_switch_status():
    """Get current kill switch status."""
    from app.pipeline import pipeline_manager
    return {"active": pipeline_manager.is_kill_switch_active()}


# ── Pipeline Endpoints ──────────────────────────────────────


class PipelineStartRequest(BaseModel):
    symbol: str
    exchange: str = "NSE"


@router.post("/pipeline/start")
async def start_pipeline(req: PipelineStartRequest):
    """Start tracking a symbol through the pipeline."""
    from app.pipeline import pipeline_manager
    try:
        session = await pipeline_manager.start_tracking(req.symbol, req.exchange)
        return {
            "status": True,
            "message": f"Pipeline started for {req.symbol}:{req.exchange}",
            "session": session.get_status(),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/pipeline/stop")
async def stop_pipeline(req: PipelineStartRequest):
    """Stop tracking a symbol."""
    from app.pipeline import pipeline_manager
    await pipeline_manager.stop_tracking(req.symbol, req.exchange)
    return {"status": True, "message": f"Pipeline stopped for {req.symbol}:{req.exchange}"}


@router.get("/pipeline/status")
async def get_pipeline_status():
    """Get pipeline status for all active sessions."""
    from app.pipeline import pipeline_manager
    return await pipeline_manager.get_status()


@router.get("/pipeline/asset-detail/{symbol}")
async def get_asset_detail(
    symbol: str,
    exchange: str = Query("NFO"),
):
    """Consolidated asset detail: signals, orders, positions, analysis, lot size."""
    from app.pipeline import pipeline_manager
    from app.database import async_session
    from app.pipeline import db_persistence as db

    # Get pipeline session summary
    session_obj = pipeline_manager.get_session(symbol, exchange)
    summary = session_obj.get_summary() if session_obj else None
    analysis = session_obj.latest_analysis if session_obj else None
    alignment = session_obj.alignment if session_obj else None
    trading_plan = session_obj.get_trading_plan() if session_obj else None

    # Get instrument info + lot size
    instrument_id = None
    lot_size = 1
    async with async_session() as dbsession:
        from sqlalchemy import select
        from app.models.market import Instrument
        stmt = select(Instrument).where(
            Instrument.symbol == symbol,
            Instrument.exchange == exchange,
        )
        result = await dbsession.execute(stmt)
        inst = result.scalar_one_or_none()
        if inst:
            instrument_id = inst.id
            lot_size = getattr(inst, "lot_size", 1) or 1

    # If lot_size is 1 for F&O, try scrip master
    if lot_size <= 1 and exchange in ("NFO", "MCX"):
        try:
            from app.broker.instruments import download_scrip_master, lookup_token
            scrip_df = await download_scrip_master()
            match = scrip_df[scrip_df["symbol"].str.contains(symbol, case=False, na=False)]
            if not match.empty and "lotsize" in match.columns:
                ls = int(match.iloc[0].get("lotsize", 1))
                if ls > 0:
                    lot_size = ls
        except Exception:
            pass

    # DB queries
    signals = []
    orders = []
    positions = []
    async with async_session() as dbsession:
        if instrument_id:
            signals = await db.load_recent_signals(dbsession, instrument_id, limit=30)
        orders = await db.load_orders_by_symbol(dbsession, symbol, limit=30)
        positions = await db.load_positions_by_symbol(dbsession, symbol, limit=30)

    # Position sizing defaults
    ltp = summary.get("ltp") if summary else None
    entry = summary.get("entry_price") if summary else None
    stop = summary.get("stop_price") if summary else None
    risk_per_share = abs(entry - stop) if entry and stop else None
    max_risk_amount = 100000 * 0.02  # 2% of 1L
    raw_shares = int(max_risk_amount / risk_per_share) if risk_per_share and risk_per_share > 0 else 0
    lots = raw_shares // lot_size if lot_size > 0 else raw_shares
    adjusted_shares = lots * lot_size

    return {
        "symbol": symbol,
        "exchange": exchange,
        "lot_size": lot_size,
        "lot_value": round(lot_size * ltp, 2) if ltp else None,
        "summary": summary,
        "analysis": analysis,
        "alignment": alignment,
        "trading_plan": trading_plan,
        "sizing": {
            "equity": 100000,
            "risk_pct": 2.0,
            "entry_price": entry,
            "stop_price": stop,
            "risk_per_share": round(risk_per_share, 2) if risk_per_share else None,
            "max_risk_amount": round(max_risk_amount, 2),
            "raw_shares": raw_shares,
            "lots": lots,
            "adjusted_shares": adjusted_shares,
            "position_value": round(adjusted_shares * entry, 2) if entry else None,
        },
        "signals": signals,
        "orders": orders,
        "positions": positions,
        "contract": session_obj.contract_symbol if session_obj else None,
        "expiry_date": session_obj.expiry_date.strftime("%Y-%m-%d") if session_obj and session_obj.expiry_date else None,
        "days_to_expiry": (session_obj.expiry_date - __import__("datetime").datetime.now()).days if session_obj and session_obj.expiry_date else None,
        "rollover_history": [],  # Populated below
    }

    # Load rollover history
    try:
        async with async_session() as dbsession:
            result["rollover_history"] = await db.load_rollover_history(dbsession, symbol, limit=10)
    except Exception:
        pass

    return result


@router.get("/pipeline/performance")
async def get_performance():
    """Portfolio performance metrics: equity curve, win rate, drawdown, R-multiples."""
    from app.database import async_session
    from app.pipeline import db_persistence as db
    from app.models.trade import Trade, Order, Position
    from sqlalchemy import select, and_, func
    from datetime import datetime, timedelta

    async with async_session() as dbsession:
        # All completed trades
        stmt = select(Trade).order_by(Trade.created_at)
        result = await dbsession.execute(stmt)
        trades = result.scalars().all()

        # All closed positions for P&L
        stmt2 = select(Position).where(Position.status == "CLOSED").order_by(Position.closed_at)
        result2 = await dbsession.execute(stmt2)
        closed_positions = result2.scalars().all()

        # Open positions
        stmt3 = select(Position).where(Position.status == "OPEN")
        result3 = await dbsession.execute(stmt3)
        open_positions = result3.scalars().all()

    # Calculate metrics
    starting_equity = 100000
    equity = starting_equity
    equity_curve = [{"date": "start", "equity": equity}]
    wins = 0
    losses = 0
    total_pnl = 0
    gross_profit = 0
    gross_loss = 0
    r_multiples = []
    max_equity = equity
    max_drawdown = 0
    trade_details = []

    for pos in closed_positions:
        if not pos.entry_price or pos.entry_price <= 0:
            continue
        if pos.direction == "LONG":
            pnl = ((pos.current_price or pos.entry_price) - pos.entry_price) * pos.quantity
        else:
            pnl = (pos.entry_price - (pos.current_price or pos.entry_price)) * pos.quantity

        equity += pnl
        total_pnl += pnl

        if pnl >= 0:
            wins += 1
            gross_profit += pnl
        else:
            losses += 1
            gross_loss += abs(pnl)

        # R-multiple (reward / risk)
        risk = abs(pos.entry_price - (pos.stop_price or pos.entry_price)) * pos.quantity
        r_mult = pnl / risk if risk > 0 else 0

        r_multiples.append(round(r_mult, 2))
        max_equity = max(max_equity, equity)
        drawdown = (max_equity - equity) / max_equity * 100 if max_equity > 0 else 0
        max_drawdown = max(max_drawdown, drawdown)

        date_str = pos.closed_at.strftime("%Y-%m-%d %H:%M") if pos.closed_at else "?"
        equity_curve.append({"date": date_str, "equity": round(equity, 2)})

        trade_details.append({
            "symbol": pos.symbol,
            "direction": pos.direction,
            "entry": pos.entry_price,
            "exit": pos.current_price,
            "qty": pos.quantity,
            "pnl": round(pnl, 2),
            "r_multiple": round(r_mult, 2),
            "mode": pos.mode,
            "date": date_str,
        })

    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    avg_win = gross_profit / wins if wins > 0 else 0
    avg_loss = gross_loss / losses if losses > 0 else 0
    profit_factor = min(gross_profit / gross_loss, 999.99) if gross_loss > 0 else 999.99 if gross_profit > 0 else 0
    expectancy = (win_rate/100 * avg_win) - ((1 - win_rate/100) * avg_loss) if total_trades > 0 else 0

    # Unrealized P&L from open positions
    unrealized_pnl = 0
    for pos in open_positions:
        if pos.direction == "LONG":
            unrealized_pnl += ((pos.current_price or pos.entry_price) - pos.entry_price) * pos.quantity
        else:
            unrealized_pnl += (pos.entry_price - (pos.current_price or pos.entry_price)) * pos.quantity

    # ── Institutional-grade metrics ──
    import math

    # Daily returns from equity curve for Sharpe/Sortino
    daily_returns = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]["equity"]
        curr = equity_curve[i]["equity"]
        if prev > 0:
            daily_returns.append((curr - prev) / prev)

    sharpe_ratio = None
    sortino_ratio = None
    calmar_ratio = None

    if len(daily_returns) >= 5:
        mean_r = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns)
        std_r = math.sqrt(variance) if variance > 0 else 0.001

        # Sharpe (annualized, assuming ~252 trading days)
        sharpe_ratio = round(mean_r / std_r * math.sqrt(252), 2)

        # Sortino (downside deviation only)
        neg_returns = [r for r in daily_returns if r < 0]
        if neg_returns:
            downside_var = sum(r ** 2 for r in neg_returns) / len(daily_returns)
            downside_std = math.sqrt(downside_var) if downside_var > 0 else 0.001
            sortino_ratio = round(mean_r / downside_std * math.sqrt(252), 2)

        # Calmar (CAGR / max drawdown)
        if max_drawdown > 0 and total_pnl != 0:
            cagr = ((equity / starting_equity) ** (252 / max(len(daily_returns), 1)) - 1) * 100
            calmar_ratio = round(cagr / max_drawdown, 2)

    # SQN from R-multiples
    sqn = None
    sqn_rating = "insufficient_data"
    if len(r_multiples) >= 30:
        mean_rm = sum(r_multiples) / len(r_multiples)
        var_rm = sum((r - mean_rm) ** 2 for r in r_multiples) / len(r_multiples)
        std_rm = math.sqrt(var_rm) if var_rm > 0 else 0.001
        sqn = round(math.sqrt(len(r_multiples)) * mean_rm / std_rm, 2)
        if sqn >= 7.0: sqn_rating = "holy_grail"
        elif sqn >= 5.1: sqn_rating = "superb"
        elif sqn >= 3.0: sqn_rating = "excellent"
        elif sqn >= 2.5: sqn_rating = "good"
        elif sqn >= 2.0: sqn_rating = "average"
        elif sqn >= 1.6: sqn_rating = "below_average"
        else: sqn_rating = "poor"

    return {
        "starting_equity": starting_equity,
        "current_equity": round(equity, 2),
        "total_pnl": round(total_pnl, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "expectancy": round(expectancy, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        # Institutional metrics
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "calmar_ratio": calmar_ratio,
        "sqn": sqn,
        "sqn_rating": sqn_rating,
        "r_multiples": r_multiples,
        "equity_curve": equity_curve,
        "open_positions": len(open_positions),
        "recent_trades": trade_details[-20:],
    }


@router.get("/pipeline/contracts")
async def get_contracts():
    """Contract expiry status for all tracked instruments."""
    from app.pipeline import pipeline_manager
    return {"contracts": pipeline_manager.get_contract_status()}


@router.get("/pipeline/command-center")
async def get_command_center():
    """Compact summary of all active sessions for the dashboard command center."""
    from app.pipeline import pipeline_manager
    summaries = pipeline_manager.get_all_summaries()
    return {"assets": summaries, "count": len(summaries)}


@router.get("/pipeline/asset-settings")
async def get_asset_settings(
    user_id: int = Query(None, description="User ID (admin can query any user)"),
):
    """Get per-asset trading mode settings for a user."""
    from app.database import async_session
    from sqlalchemy import select
    from app.models.user import UserAssetSettings

    async with async_session() as session:
        stmt = select(UserAssetSettings)
        if user_id:
            stmt = stmt.where(UserAssetSettings.user_id == user_id)
        result = await session.execute(stmt)
        settings_list = result.scalars().all()

    return {
        "settings": [
            {
                "id": s.id,
                "user_id": s.user_id,
                "symbol": s.symbol,
                "exchange": s.exchange,
                "trading_mode": s.trading_mode,
                "is_active": s.is_active,
                "screen1_timeframe": s.screen1_timeframe,
                "screen2_timeframe": s.screen2_timeframe,
                "screen3_timeframe": s.screen3_timeframe,
                "max_risk_pct_override": s.max_risk_pct_override,
            }
            for s in settings_list
        ]
    }


class AssetConfigRequest(BaseModel):
    exchange: str = "NFO"
    trading_mode: Optional[str] = None  # PAPER or LIVE
    is_active: Optional[bool] = None
    screen1_timeframe: Optional[str] = None  # e.g. "1w", "1d"
    screen2_timeframe: Optional[str] = None  # e.g. "1d", "1h"
    screen3_timeframe: Optional[str] = None  # e.g. "1h", "15m"
    max_risk_pct_override: Optional[float] = None
    user_id: int = 1


@router.put("/pipeline/asset-settings/{symbol}")
async def update_asset_settings(symbol: str, req: AssetConfigRequest):
    """Update per-asset configuration: mode, timeframes, risk.

    When timeframes change, the running pipeline session is restarted with
    new timeframes — historical data is reloaded and indicators recomputed.
    """
    from app.database import async_session
    from sqlalchemy import select
    from app.models.user import UserAssetSettings, User

    VALID_TIMEFRAMES = {"1w", "1d", "4h", "1h", "30m", "15m", "5m", "1m"}

    # Validate timeframes
    for tf_field in [req.screen1_timeframe, req.screen2_timeframe, req.screen3_timeframe]:
        if tf_field and tf_field not in VALID_TIMEFRAMES:
            raise HTTPException(400, f"Invalid timeframe: {tf_field}. Valid: {VALID_TIMEFRAMES}")

    async with async_session() as session:
        # Verify LIVE approval
        if req.trading_mode == "LIVE":
            user_result = await session.execute(select(User).where(User.id == req.user_id))
            user = user_result.scalar_one_or_none()
            if not user or not user.approved_for_live:
                raise HTTPException(403, "User not approved for LIVE trading.")

        # Find or create settings
        stmt = select(UserAssetSettings).where(
            UserAssetSettings.user_id == req.user_id,
            UserAssetSettings.symbol == symbol,
            UserAssetSettings.exchange == req.exchange,
        )
        result = await session.execute(stmt)
        asset_settings = result.scalar_one_or_none()

        if not asset_settings:
            asset_settings = UserAssetSettings(
                user_id=req.user_id, symbol=symbol, exchange=req.exchange,
            )
            session.add(asset_settings)

        # Track if timeframes changed (need pipeline restart)
        tf_changed = False
        old_tfs = {
            "1": asset_settings.screen1_timeframe,
            "2": asset_settings.screen2_timeframe,
            "3": asset_settings.screen3_timeframe,
        }

        if req.trading_mode is not None:
            asset_settings.trading_mode = req.trading_mode
        if req.is_active is not None:
            asset_settings.is_active = req.is_active
        if req.screen1_timeframe is not None:
            if asset_settings.screen1_timeframe != req.screen1_timeframe:
                tf_changed = True
            asset_settings.screen1_timeframe = req.screen1_timeframe
        if req.screen2_timeframe is not None:
            if asset_settings.screen2_timeframe != req.screen2_timeframe:
                tf_changed = True
            asset_settings.screen2_timeframe = req.screen2_timeframe
        if req.screen3_timeframe is not None:
            if asset_settings.screen3_timeframe != req.screen3_timeframe:
                tf_changed = True
            asset_settings.screen3_timeframe = req.screen3_timeframe
        if req.max_risk_pct_override is not None:
            asset_settings.max_risk_pct_override = req.max_risk_pct_override

        await session.commit()
        await session.refresh(asset_settings)

    # Apply to running pipeline
    from app.pipeline import pipeline_manager
    pipe_session = (
        pipeline_manager._sessions.get(f"{symbol}:{req.exchange}:u{req.user_id}")
        or pipeline_manager._sessions.get(f"{symbol}:{req.exchange}")
    )

    restart_needed = False

    if pipe_session and pipe_session.active:
        # Update trading mode
        if req.trading_mode is not None:
            pipe_session._asset_trading_mode = asset_settings.trading_mode

        # If timeframes changed, restart the session to reload data
        if tf_changed:
            new_tfs = {}
            if asset_settings.screen1_timeframe:
                new_tfs["1"] = asset_settings.screen1_timeframe
            if asset_settings.screen2_timeframe:
                new_tfs["2"] = asset_settings.screen2_timeframe
            if asset_settings.screen3_timeframe:
                new_tfs["3"] = asset_settings.screen3_timeframe

            if new_tfs:
                restart_needed = True
                logger.info(
                    "Timeframe change for {} — restarting pipeline: {} → {}",
                    symbol, old_tfs, new_tfs,
                )
                # Stop and restart with new timeframes
                await pipeline_manager.stop_tracking(symbol, req.exchange)
                new_session = await pipeline_manager.start_tracking(
                    symbol, req.exchange, user_id=req.user_id,
                )
                # Override timeframes on the new session
                new_session.screen_timeframes.update(new_tfs)
                new_session._asset_trading_mode = asset_settings.trading_mode
                # Reload historical data + recompute indicators
                await new_session._load_historical()
                for tf, df in new_session.candle_buffers.items():
                    if not df.empty:
                        screen_num = new_session._tf_to_screen(tf)
                        engine = new_session._engines.get(tf)
                        if engine:
                            new_session.indicators[tf] = engine.compute_for_screen(df, screen_num)
                logger.info("Pipeline restarted for {} with new timeframes: {}", symbol, new_tfs)

    return {
        "symbol": symbol,
        "exchange": req.exchange,
        "trading_mode": asset_settings.trading_mode,
        "is_active": asset_settings.is_active,
        "screen1_timeframe": asset_settings.screen1_timeframe,
        "screen2_timeframe": asset_settings.screen2_timeframe,
        "screen3_timeframe": asset_settings.screen3_timeframe,
        "max_risk_pct_override": asset_settings.max_risk_pct_override,
        "restarted": restart_needed,
    }


@router.get("/pipeline/signals")
async def get_pipeline_signals(limit: int = Query(20, ge=1, le=100)):
    """Get recent signals from DB."""
    from app.database import async_session
    from app.pipeline import db_persistence as db
    async with async_session() as session:
        return {"signals": await db.load_recent_signals(session, limit=limit)}


@router.get("/pipeline/analysis/{symbol}")
async def get_pipeline_analysis(symbol: str, exchange: str = Query("NSE")):
    """Get latest Triple Screen analysis for an active pipeline session."""
    from app.pipeline import pipeline_manager
    session = pipeline_manager.get_session(symbol, exchange)
    if not session or not session.active:
        raise HTTPException(
            status_code=404,
            detail=f"No active pipeline session for {symbol}:{exchange}",
        )
    return {
        "symbol": symbol,
        "exchange": exchange,
        "analysis": session.latest_analysis,
        "status": session.get_status(),
    }
