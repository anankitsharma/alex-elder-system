"""Trading API endpoints — orders, positions, holdings."""

from datetime import datetime
from enum import Enum
from typing import Literal

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, field_validator
from loguru import logger

from app.broker.angel_client import angel
from app.config import settings
from app.database import async_session

router = APIRouter(prefix="/api/trading", tags=["trading"])

# In-memory paper order book (persists for server lifetime)
_paper_orders: list[dict] = []
_paper_positions: list[dict] = []

# Paper mode capital tracking
_paper_capital = {
    "starting": 100000.00,
    "available": 100000.00,
    "utilized": 0.00,
}


class OrderRequest(BaseModel):
    symbol: str
    token: str
    exchange: Literal["NSE", "NFO", "BSE", "MCX", "CDS"] = "NSE"
    direction: Literal["BUY", "SELL"]
    order_type: Literal["MARKET", "LIMIT", "SL", "SL-M"] = "MARKET"
    quantity: int
    price: float = 0
    trigger_price: float = 0
    product_type: Literal["DELIVERY", "INTRADAY", "CARRYFORWARD", "BO", "CO"] = "DELIVERY"

    @field_validator("symbol")
    @classmethod
    def symbol_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 50:
            raise ValueError("symbol must be 1-50 characters")
        return v

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("quantity must be greater than 0")
        if v > 999999:
            raise ValueError("quantity exceeds maximum (999999)")
        return v

    @field_validator("price")
    @classmethod
    def price_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("price cannot be negative")
        return round(v, 2)

    @field_validator("trigger_price")
    @classmethod
    def trigger_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("trigger_price cannot be negative")
        return round(v, 2)


def _safe_broker_call(fn, fallback=None):
    """Call a broker function with graceful error handling."""
    try:
        result = fn()
        # Angel One returns {"success":false,"message":"Invalid Token"} on expired session
        if isinstance(result, dict) and result.get("message") == "Invalid Token":
            logger.warning("Angel One session expired — returning empty data")
            return fallback if fallback is not None else {"data": [], "status": False, "message": "Session expired — restart backend to re-login"}
        return result
    except RuntimeError as e:
        # Client not logged in
        logger.warning("Broker not connected: {}", e)
        return fallback if fallback is not None else {"data": [], "status": False, "message": str(e)}
    except Exception as e:
        logger.error("Broker call failed: {}", e)
        return fallback if fallback is not None else {"data": [], "status": False, "message": str(e)}


@router.get("/profile")
async def get_profile():
    """Get Angel One account profile."""
    return _safe_broker_call(lambda: angel.get_profile(), {"data": {}})


@router.get("/funds")
async def get_funds():
    """Get available funds and margins. In PAPER mode, reads from DB equity."""
    if settings.trading_mode == "PAPER":
        # Get real equity from portfolio_risk DB (includes realized P&L)
        from app.pipeline import db_persistence as db
        try:
            async with async_session() as session:
                current_equity = await db.get_current_equity(session, user_id=1)
        except Exception:
            current_equity = settings.paper_starting_capital

        # Calculate utilized margin and unrealized P&L from DB positions
        utilized = 0.0
        unrealized_pnl = 0.0
        try:
            from app.models.trade import Position
            from sqlalchemy import select
            async with async_session() as session:
                result = await session.execute(
                    select(Position).where(Position.status == "OPEN")
                )
                for pos in result.scalars().all():
                    # Margin tied up = entry_price * quantity
                    utilized += abs(pos.quantity * pos.entry_price)
                    # Unrealized P&L from mark-to-market (updated by pipeline)
                    unrealized_pnl += pos.unrealized_pnl or 0.0
        except Exception:
            pass

        # Also include in-memory paper positions (manual trades via /order)
        utilized += sum(
            abs(int(p.get("netqty", "0"))) * float(p.get("ltp", "0"))
            for p in _paper_positions
        )
        realized_pnl_inmem = sum(float(p.get("pnl", "0")) for p in _paper_positions)

        # Net = equity (includes realized) + unrealized from open positions
        net = round(current_equity + unrealized_pnl + realized_pnl_inmem, 2)
        utilized = round(utilized, 2)
        available = round(net - utilized, 2)

        return {
            "status": True,
            "data": {
                "availablecash": f"{available:.2f}",
                "utilisedmargin": f"{utilized:.2f}",
                "availableintradaypayin": f"{available:.2f}",
                "collateral": "0.00",
                "m2mrealized": f"{realized_pnl_inmem:.2f}",
                "m2munrealized": f"{unrealized_pnl:.2f}",
                "net": f"{net:.2f}",
            },
        }
    return _safe_broker_call(lambda: angel.get_rms())


@router.get("/holdings")
async def get_holdings():
    """Get current holdings."""
    return _safe_broker_call(lambda: angel.get_holdings(), {"data": []})


@router.get("/positions")
async def get_positions():
    """Get current positions — merges in-memory paper + DB pipeline positions."""
    if settings.trading_mode == "PAPER":
        # Merge in-memory paper positions with DB pipeline positions
        combined = list(_paper_positions)
        try:
            from app.models.trade import Position
            from sqlalchemy import select
            async with async_session() as session:
                result = await session.execute(
                    select(Position).where(Position.status == "OPEN").order_by(Position.opened_at.desc())
                )
                for pos in result.scalars().all():
                    # Calculate unrealized P&L
                    if pos.direction == "LONG":
                        pnl = ((pos.current_price or pos.entry_price) - pos.entry_price) * pos.quantity
                    else:
                        pnl = (pos.entry_price - (pos.current_price or pos.entry_price)) * pos.quantity
                    combined.append({
                        "tradingsymbol": pos.symbol,
                        "symboltoken": "",
                        "exchange": "",
                        "transactiontype": "BUY" if pos.direction == "LONG" else "SELL",
                        "netqty": str(pos.quantity if pos.direction == "LONG" else -pos.quantity),
                        "quantity": str(pos.quantity),
                        "buyavgprice": f"{pos.entry_price:.2f}" if pos.direction == "LONG" else "0",
                        "sellavgprice": f"{pos.entry_price:.2f}" if pos.direction == "SHORT" else "0",
                        "ltp": f"{pos.current_price or pos.entry_price:.2f}",
                        "pnl": f"{pnl:.2f}",
                        "stoploss": f"{pos.stop_price:.2f}" if pos.stop_price else "0",
                        "target": f"{pos.target_price:.2f}" if pos.target_price else "0",
                        "status": "OPEN",
                        "mode": pos.mode,
                        "source": "pipeline",
                    })
        except Exception:
            pass
        return {"data": combined}
    return _safe_broker_call(lambda: angel.get_positions(), {"data": []})


@router.get("/orders")
async def get_order_book():
    """Get order book — merges in-memory paper + DB pipeline orders."""
    if settings.trading_mode == "PAPER":
        combined = list(_paper_orders)
        try:
            from app.models.trade import Order
            from sqlalchemy import select
            async with async_session() as session:
                result = await session.execute(
                    select(Order).order_by(Order.created_at.desc()).limit(50)
                )
                for o in result.scalars().all():
                    combined.append({
                        "orderid": o.order_id or f"DB-{o.id}",
                        "tradingsymbol": o.symbol,
                        "transactiontype": o.direction,
                        "ordertype": o.order_type,
                        "quantity": str(o.quantity),
                        "price": f"{o.price:.2f}" if o.price else "0",
                        "triggerprice": "0",
                        "status": o.status.lower() if o.status else "complete",
                        "filledshares": str(o.filled_quantity or 0),
                        "averageprice": f"{o.filled_price:.2f}" if o.filled_price else "0",
                        "mode": o.mode,
                        "source": "pipeline",
                        "text": f"{o.created_at.strftime('%H:%M:%S')}" if o.created_at else "",
                    })
        except Exception:
            pass
        return {"data": combined}
    return _safe_broker_call(lambda: angel.get_order_book(), {"data": []})


@router.post("/order")
async def create_order(req: OrderRequest):
    """Place a new order with validation and risk checks."""
    # Validate: LIMIT orders must have a price
    if req.order_type == "LIMIT" and req.price <= 0:
        raise HTTPException(status_code=400, detail="LIMIT orders require a price > 0")
    if req.order_type in ("SL", "SL-M") and req.trigger_price <= 0:
        raise HTTPException(status_code=400, detail="SL orders require trigger_price > 0")

    # Risk check: max position value
    order_value = req.quantity * (req.price if req.price > 0 else 1000)  # est. for MARKET
    if settings.trading_mode == "PAPER":
        available = _paper_capital["available"]
        if order_value > available and req.direction == "BUY":
            raise HTTPException(status_code=400, detail=f"Insufficient funds: order value ~{order_value:.0f} > available {available:.0f}")

    if settings.trading_mode == "PAPER":
        order = {
            "orderid": f"PAPER-{len(_paper_orders)+1:04d}",
            "tradingsymbol": req.symbol,
            "transactiontype": req.direction,
            "ordertype": req.order_type,
            "quantity": str(req.quantity),
            "price": str(req.price),
            "status": "complete",
            "text": "Paper order filled",
            "updatetime": datetime.now().strftime("%d-%b-%Y %H:%M:%S"),
        }
        _paper_orders.append(order)

        # Track as position if BUY
        existing = next((p for p in _paper_positions if p.get("tradingsymbol") == req.symbol), None)
        if existing:
            qty = int(existing.get("netqty", "0"))
            delta = req.quantity if req.direction == "BUY" else -req.quantity
            existing["netqty"] = str(qty + delta)
            existing["ltp"] = str(req.price)
            if int(existing["netqty"]) == 0:
                _paper_positions.remove(existing)
        else:
            _paper_positions.append({
                "tradingsymbol": req.symbol,
                "exchange": req.exchange,
                "producttype": req.product_type,
                "netqty": str(req.quantity if req.direction == "BUY" else -req.quantity),
                "buyavgprice": str(req.price) if req.direction == "BUY" else "0",
                "sellavgprice": str(req.price) if req.direction == "SELL" else "0",
                "ltp": str(req.price),
                "pnl": "0.00",
            })

        # Write-through to DB for persistence across restarts
        try:
            from app.pipeline import db_persistence as db_p
            async with async_session() as db_sess:
                await db_p.save_order(db_sess, {
                    "instrument_id": 0,
                    "symbol": req.symbol,
                    "order_id": order["orderid"],
                    "direction": req.direction,
                    "order_type": req.order_type,
                    "quantity": req.quantity,
                    "price": req.price,
                    "status": "COMPLETE",
                    "mode": "PAPER",
                    "filled_price": req.price,
                    "filled_quantity": req.quantity,
                })
        except Exception as e:
            logger.warning("DB order write-through failed: {}", e)

        return {
            "status": True,
            "mode": "PAPER",
            "message": f"Paper {req.direction} order filled: {req.symbol} x{req.quantity} @ {req.price}",
            "order": order,
        }

    try:
        from app.broker.orders import place_order
        result = place_order(
            symbol=req.symbol, token=req.token, exchange=req.exchange,
            direction=req.direction, order_type=req.order_type,
            quantity=req.quantity, price=req.price,
            trigger_price=req.trigger_price, product_type=req.product_type,
        )
        return result
    except Exception as e:
        return {"status": False, "message": str(e)}


@router.delete("/order/{order_id}")
async def delete_order(order_id: str):
    """Cancel an order."""
    if settings.trading_mode == "PAPER":
        for o in _paper_orders:
            if o.get("orderid") == order_id:
                o["status"] = "cancelled"
                return {"status": True, "message": f"Paper order {order_id} cancelled"}
        return {"status": False, "message": "Order not found"}

    try:
        from app.broker.orders import cancel_order
        return cancel_order(order_id)
    except Exception as e:
        return {"status": False, "message": str(e)}


@router.get("/mode")
async def get_trading_mode():
    """Get current trading mode (PAPER or LIVE)."""
    return {"mode": settings.trading_mode}


@router.post("/paper/reset")
async def reset_paper_account():
    """Reset paper trading account to starting state."""
    if settings.trading_mode != "PAPER":
        raise HTTPException(status_code=400, detail="Only available in PAPER mode")
    _paper_orders.clear()
    _paper_positions.clear()
    _paper_capital["available"] = settings.paper_starting_capital
    _paper_capital["utilized"] = 0.0
    return {"status": True, "message": f"Paper account reset to {settings.paper_starting_capital:,.0f}"}


@router.post("/session/refresh")
async def refresh_session():
    """Force re-login to Angel One APIs (use when session expires)."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    _pool = ThreadPoolExecutor(max_workers=1)
    loop = asyncio.get_event_loop()
    try:
        success = await asyncio.wait_for(
            loop.run_in_executor(_pool, angel.login_all),
            timeout=30,
        )
        # Reset broker offline flag in charts module
        try:
            from app.api.charts import _broker_offline, _broker_fail_count
            import app.api.charts as charts_mod
            charts_mod._broker_offline = False
            charts_mod._broker_fail_count = 0
        except Exception:
            pass

        if success:
            logger.info("Session refresh successful")
            return {"status": True, "message": "All sessions refreshed"}
        else:
            logger.warning("Session refresh partially failed")
            return {"status": False, "message": "Some sessions failed to refresh"}
    except asyncio.TimeoutError:
        return {"status": False, "message": "Session refresh timed out (30s)"}
    except Exception as e:
        return {"status": False, "message": f"Refresh error: {e}"}
    finally:
        _pool.shutdown(wait=False)
