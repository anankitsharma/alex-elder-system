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
