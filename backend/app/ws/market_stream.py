"""WebSocket endpoints for live market data and pipeline events."""

import asyncio
import json
import time as _time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

router = APIRouter()

# ── Main event loop reference (set at startup) ───────────────
_main_loop: asyncio.AbstractEventLoop | None = None

# Thread-safe tick queue: feed thread appends, async poller consumes
import collections
_tick_queue: collections.deque = collections.deque(maxlen=10000)  # Thread-safe, bounded
_tick_poller_task: asyncio.Task | None = None

def set_main_loop(loop: asyncio.AbstractEventLoop):
    """Store reference to the main asyncio event loop for thread-safe scheduling."""
    global _main_loop
    _main_loop = loop

def start_tick_poller():
    """No-op — tick processing is now handled by _heartbeat_loop."""
    pass

# ── Raw tick stream (/ws/market) ─────────────────────────────

# Connected frontend clients for raw ticks
_clients: list[WebSocket] = []

# Latest tick data cache (token -> latest data)
_tick_cache: dict[str, dict] = {}

# ── Heartbeat for pipeline clients ───────────────────────────
_heartbeat_task: asyncio.Task | None = None
HEARTBEAT_INTERVAL = 15  # seconds


async def broadcast_tick(data: dict):
    """Broadcast a tick to all connected WebSocket clients."""
    token = str(data.get("token", ""))
    _tick_cache[token] = data

    message = json.dumps(data, default=str)
    disconnected = []
    for ws in _clients:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)

    for ws in disconnected:
        _clients.remove(ws)


def on_tick_received(tick_data: Any):
    """Callback for MarketFeed — schedules broadcast to WebSocket clients.

    This runs in SmartWebSocketV2's thread, so we use the stored main loop
    reference with call_soon_threadsafe to schedule the async broadcast.
    """
    if isinstance(tick_data, dict):
        data = tick_data
    else:
        try:
            data = json.loads(tick_data) if isinstance(tick_data, str) else tick_data
        except (json.JSONDecodeError, TypeError):
            return

    # Validate tick data before queueing
    ltp = data.get("ltp") or data.get("last_traded_price")
    if ltp is not None:
        try:
            ltp_f = float(ltp)
            if ltp_f <= 0 or ltp_f > 1e7:
                return  # Invalid price — skip
        except (ValueError, TypeError):
            return
    token = data.get("token")
    if not token:
        return  # No token — skip

    # Queue the tick for the async poller to pick up (avoids cross-thread async issues on Windows)
    _tick_queue.append(data)


@router.websocket("/ws/market")
async def market_websocket(websocket: WebSocket):
    """WebSocket endpoint for frontend to receive live market data."""
    await websocket.accept()
    _clients.append(websocket)
    logger.info("Market WS client connected (total: {})", len(_clients))

    try:
        # Send cached ticks on connect
        for tick in _tick_cache.values():
            await websocket.send_text(json.dumps(tick, default=str))

        # Keep connection alive and handle client messages
        while True:
            msg = await websocket.receive_text()
            # Client can send subscription requests here
            try:
                request = json.loads(msg)
                if request.get("action") == "subscribe":
                    # Handle dynamic subscriptions
                    logger.info("Client subscription request: {}", request)
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        pass
    finally:
        if websocket in _clients:
            _clients.remove(websocket)
        logger.info("Market WS client disconnected (total: {})", len(_clients))


# ── Pipeline event stream (/ws/pipeline) ─────────────────────

_pipeline_clients: list[WebSocket] = []

# Per-user connection tracking (multi-user support)
_user_connections: dict[int, list[WebSocket]] = {}  # user_id -> [ws1, ws2, ...]
_ws_user_map: dict[int, int] = {}  # id(ws) -> user_id


async def _heartbeat_loop():
    """Combined tick processor + heartbeat sender.

    Polls tick queue every 50ms for live data routing.
    Sends heartbeat to pipeline clients every HEARTBEAT_INTERVAL.
    """
    from app.pipeline import pipeline_manager
    last_heartbeat = 0.0

    while True:
        # ── Process tick queue (every 50ms) ──
        if _tick_queue:
            batch = list(_tick_queue)
            _tick_queue.clear()
            for data in batch:
                await broadcast_tick(data)
                # Route tick to pipeline session
                token = str(data.get("token", ""))
                key = pipeline_manager._token_map.get(token)
                if key and key in pipeline_manager._sessions:
                    session = pipeline_manager._sessions[key]
                    if session.active:
                        # Feed tick to candle builders
                        for tf, builder in session.candle_builders.items():
                            completed = builder.on_tick(data)
                            if completed:
                                await session._on_new_candle(tf, completed)
                        # Broadcast running bars
                        current_price = 0
                        for tf, builder in session.candle_builders.items():
                            bar = builder.running_bar
                            if bar:
                                current_price = bar.get("close", 0)
                                if session._broadcast:
                                    await session._broadcast_event("running_bar", {
                                        "symbol": session.symbol,
                                        "timeframe": tf,
                                        "bar": bar,
                                    })

                        # Check stop losses + targets (throttled: every 2s per session)
                        # Only during market hours — skip weekends/holidays
                        now = _time.time()
                        if current_price > 0:
                            from app.pipeline.market_hours import is_market_open as _mkt_open
                            if _mkt_open(session.exchange, session.symbol):
                                sl_key = f"_sl_{key}"
                                last_sl = getattr(_heartbeat_loop, sl_key, 0)
                                if now - last_sl >= 2:
                                    setattr(_heartbeat_loop, sl_key, now)
                                    await session._check_stop_losses(current_price)

        # ── Heartbeat (every HEARTBEAT_INTERVAL) ──
        now = _time.time()
        if now - last_heartbeat >= HEARTBEAT_INTERVAL and _pipeline_clients:
            last_heartbeat = now
            try:
                from app.broker.websocket_feed import market_feed
                feed_connected = market_feed.is_connected
                feed_age = market_feed.last_data_age
            except Exception:
                feed_connected = False
                feed_age = -1

            # Include broker connection state for frontend status display
            broker_state = {}
            try:
                from fastapi import FastAPI as _FA
                import app.main as _main_mod
                broker_state = getattr(_main_mod.app.state, "broker_state", {})
            except Exception:
                pass

            msg = json.dumps({
                "type": "heartbeat",
                "ts": now,
                "feed_connected": feed_connected,
                "feed_last_data_age": round(feed_age, 1),
                "broker_status": broker_state.get("status", "UNKNOWN"),
                "broker_error": broker_state.get("last_error", ""),
            })
            disconnected = []
            for ws in _pipeline_clients:
                try:
                    await ws.send_text(msg)
                except Exception:
                    disconnected.append(ws)
            for ws in disconnected:
                _pipeline_clients.remove(ws)

        # ── Periodic indicator refresh (every 30s) ──
        # Recompute indicators using running bar as latest candle
        if not hasattr(_heartbeat_loop, '_last_ind_refresh'):
            _heartbeat_loop._last_ind_refresh = 0.0
        if now - _heartbeat_loop._last_ind_refresh >= 30 and _pipeline_clients:
            _heartbeat_loop._last_ind_refresh = now
            for key, session in pipeline_manager._sessions.items():
                if not session.active:
                    continue
                try:
                    for tf in session.screen_timeframes.values():
                        # Append running bar to buffer temporarily for indicator calc
                        builder = session.candle_builders.get(tf)
                        if not builder or not builder.running_bar:
                            continue
                        engine = session._engines.get(tf)
                        df = session.candle_buffers.get(tf)
                        if engine and df is not None and not df.empty:
                            import pandas as pd
                            running = pd.DataFrame([builder.running_bar])
                            temp_df = pd.concat([df, running], ignore_index=True)
                            screen_num = session._tf_to_screen(tf)
                            indicators = engine.compute_for_screen(temp_df, screen_num)
                            await broadcast_pipeline_event({
                                "type": "indicators",
                                "symbol": session.symbol,
                                "timeframe": tf,
                                "data": indicators,
                            })
                except Exception as e:
                    logger.debug("Periodic indicator refresh failed for {}: {}", key, e)

        # ── Command center broadcast (every 5s) ──
        if not hasattr(_heartbeat_loop, '_last_cc'):
            _heartbeat_loop._last_cc = 0.0
        if now - _heartbeat_loop._last_cc >= 5 and _pipeline_clients:
            _heartbeat_loop._last_cc = now
            try:
                summaries = pipeline_manager.get_all_summaries()
                if summaries:
                    await broadcast_pipeline_event({
                        "type": "command_center",
                        "assets": summaries,
                        "ts": now,
                    })
            except Exception:
                pass

        # ── Order fill poller (every 5s, LIVE mode only) ──
        if not hasattr(_heartbeat_loop, '_last_order_poll'):
            _heartbeat_loop._last_order_poll = 0.0
        if now - _heartbeat_loop._last_order_poll >= 5:
            _heartbeat_loop._last_order_poll = now
            try:
                from app.config import settings as _cfg
                from app.pipeline.holidays import is_trading_day as _is_td2
                if _cfg.trading_mode == "LIVE" and _is_td2():
                    await _poll_order_fills(pipeline_manager)
            except Exception as e:
                logger.debug("Order fill poll error: {}", e)

        # ── EOD auto-close check (tighter near market close) ──
        if not hasattr(_heartbeat_loop, '_last_eod_check'):
            _heartbeat_loop._last_eod_check = 0.0
        # Tighter EOD check near market close (every 10s in last 10 min)
        try:
            from datetime import datetime as _dt_eod
            from app.pipeline.market_hours import IST as _IST_eod
            _now_eod = _dt_eod.now(_IST_eod)
            eod_interval = 10 if (_now_eod.hour == 15 and _now_eod.minute >= 20) else 30
        except Exception:
            eod_interval = 30
        if now - _heartbeat_loop._last_eod_check >= eod_interval:
            _heartbeat_loop._last_eod_check = now
            try:
                await _check_eod_close(pipeline_manager)
            except Exception as e:
                logger.debug("EOD check error: {}", e)

        # ── Daily P&L summary (once per day after NSE close) ──
        if not hasattr(_heartbeat_loop, '_last_daily_summary'):
            _heartbeat_loop._last_daily_summary = ""
        try:
            from datetime import datetime as _dt
            from app.pipeline.market_hours import IST as _IST
            _now_ist = _dt.now(_IST)
            _today = _now_ist.strftime("%Y-%m-%d")
            _t = _now_ist.time()
            # Send at 15:35 IST (5 min after NSE close), trading days only
            from app.pipeline.holidays import is_trading_day as _is_td
            if (_t.hour == 15 and 35 <= _t.minute <= 36
                    and _is_td(_now_ist.date())
                    and _heartbeat_loop._last_daily_summary != _today):
                _heartbeat_loop._last_daily_summary = _today
                await _send_daily_summary(_today)

            # ── Daily broker session logout (SEBI compliance, after market close) ──
            if not hasattr(_heartbeat_loop, '_last_session_logout'):
                _heartbeat_loop._last_session_logout = ""
            if (_t.hour == 15 and 40 <= _t.minute <= 41
                    and _is_td(_now_ist.date())
                    and _heartbeat_loop._last_session_logout != _today):
                _heartbeat_loop._last_session_logout = _today
                try:
                    from app.broker.angel_client import angel
                    angel.logout()
                    logger.info("Daily session logout completed (SEBI compliance)")
                except Exception as e:
                    logger.warning("Daily session logout failed: {}", e)
        except Exception:
            pass

        # ── Contract rollover check (every 30 min) ──
        if not hasattr(_heartbeat_loop, '_last_rollover_check'):
            _heartbeat_loop._last_rollover_check = 0.0
        if now - _heartbeat_loop._last_rollover_check >= 1800:  # 30 min
            _heartbeat_loop._last_rollover_check = now
            try:
                await pipeline_manager.check_and_rollover()
            except Exception:
                pass

        await asyncio.sleep(0.05)  # 50ms poll cycle


async def _send_daily_summary(date_str: str):
    """Compute and send daily P&L summary from today's closed trades."""
    from app.database import async_session
    from app.pipeline import db_persistence as db
    from app.notifications.telegram import notify_daily_summary

    try:
        async with async_session() as session:
            month_str = date_str[:7]  # YYYY-MM
            trades = await db.load_month_trades(session, month_str)

            # Filter to today's trades only
            today_trades = [t for t in trades
                           if t.created_at and t.created_at.strftime("%Y-%m-%d") == date_str]

            if not today_trades:
                return  # No trades today, skip summary

            total_pnl = sum(t.pnl or 0 for t in today_trades)
            winners = sum(1 for t in today_trades if (t.pnl or 0) > 0)
            losers = sum(1 for t in today_trades if (t.pnl or 0) < 0)
            total = len(today_trades)
            win_rate = (winners / total * 100) if total > 0 else 0

            best = max(today_trades, key=lambda t: t.pnl or 0) if today_trades else None
            worst = min(today_trades, key=lambda t: t.pnl or 0) if today_trades else None

            # Count open positions
            positions = await db.load_open_positions(session)
            open_count = len(positions)

            await notify_daily_summary(
                date_str=date_str,
                total_trades=total,
                winners=winners,
                losers=losers,
                total_pnl=total_pnl,
                win_rate=win_rate,
                best_trade={"symbol": best.symbol, "pnl": best.pnl} if best and (best.pnl or 0) > 0 else None,
                worst_trade={"symbol": worst.symbol, "pnl": worst.pnl} if worst and (worst.pnl or 0) < 0 else None,
                open_positions=open_count,
            )
    except Exception as e:
        logger.debug("Daily summary failed: {}", e)


async def _check_eod_close(pipeline_manager):
    """Close all open positions when market is nearing close (EOD cutoff).

    Checks each active session's exchange-specific close time and triggers
    position exit when the EOD cutoff is reached.
    """
    from datetime import datetime
    from app.pipeline.market_hours import get_session, get_eod_cutoff, IST
    from app.database import async_session
    from app.pipeline import db_persistence as db

    now_ist = datetime.now(IST)

    # Skip weekends and market holidays
    from app.pipeline.holidays import is_holiday
    if is_holiday(now_ist.date()):
        return

    for key, session in pipeline_manager._sessions.items():
        if not session.active:
            continue

        cutoff = get_eod_cutoff(session.exchange, session.symbol)
        mkt_session = get_session(session.exchange, session.symbol)
        close_time = mkt_session.close_time
        current_time = now_ist.time()

        # Check if we're past EOD cutoff but before close (5-min window)
        # For sessions that close same day (not overnight)
        past_cutoff = False
        if close_time >= mkt_session.open_time:
            # Normal session (e.g., NSE 9:15-15:30)
            past_cutoff = cutoff <= current_time <= close_time
        else:
            # Overnight session — cutoff is near midnight
            past_cutoff = current_time >= cutoff or current_time <= close_time

        if not past_cutoff:
            continue

        # Check if we already did EOD close for this session today
        eod_key = f"_eod_done_{key}_{now_ist.date()}"
        if getattr(_check_eod_close, eod_key, False):
            continue
        setattr(_check_eod_close, eod_key, True)

        # Close INTRADAY positions only — POSITIONAL positions carry overnight
        try:
            async with async_session() as db_session:
                positions = await db.load_open_positions_by_symbol(db_session, session.symbol)
                for pos in positions:
                    # Skip POSITIONAL positions — they carry forward
                    pos_type = getattr(pos, "position_type", "POSITIONAL")
                    if pos_type == "POSITIONAL":
                        logger.info("EOD: {} {} position carries forward (POSITIONAL)", pos.direction, session.symbol)
                        continue
                    # Get current price from running bar
                    current_price = 0
                    for tf, builder in session.candle_builders.items():
                        bar = builder.running_bar
                        if bar:
                            current_price = bar.get("close", 0)
                            break

                    if current_price <= 0:
                        continue

                    # Place live exit order if LIVE mode
                    if pos.mode == "LIVE":
                        try:
                            from app.trading.live import LivePlacer
                            placer = LivePlacer()
                            exit_dir = "SELL" if pos.direction == "LONG" else "BUY"
                            await placer.place_exit(
                                symbol=session.symbol, token=session.token,
                                exchange=session.exchange, direction=exit_dir,
                                quantity=pos.quantity, order_type="MARKET",
                                price=current_price, product_type="CARRYFORWARD",
                            )
                        except Exception as e:
                            logger.error("LIVE EOD exit failed for {}: {}", session.symbol, e)
                            continue

                    trade = await db.close_position(db_session, pos.id, current_price)
                    if trade:
                        pnl = (current_price - pos.entry_price) * pos.quantity if pos.direction == "LONG" \
                            else (pos.entry_price - current_price) * pos.quantity
                        logger.info(
                            "EOD CLOSE: {} {} @ {:.2f} P&L={:.2f} (cutoff={})",
                            pos.direction, session.symbol, current_price, pnl, cutoff,
                        )
                        await broadcast_pipeline_event({
                            "type": "position_closed",
                            "symbol": session.symbol,
                            "direction": pos.direction,
                            "entry_price": pos.entry_price,
                            "exit_price": current_price,
                            "quantity": pos.quantity,
                            "pnl": round(pnl, 2),
                            "reason": "EOD",
                        })
                        # Notification
                        try:
                            from app.notifications.telegram import notify_position_closed
                            await notify_position_closed(
                                symbol=session.symbol,
                                direction=pos.direction,
                                entry_price=pos.entry_price,
                                exit_price=current_price,
                                quantity=pos.quantity,
                                pnl=round(pnl, 2),
                                reason="EOD",
                                stop_price=pos.stop_price or 0,
                                target_price=pos.target_price or 0,
                                mode=pos.mode or "PAPER",
                            )
                        except Exception:
                            pass
        except Exception as e:
            logger.error("EOD close failed for {}: {}", session.symbol, e)


async def _poll_order_fills(pipeline_manager):
    """Poll Angel One order book and update pending orders with fill status.

    Runs every 5s in LIVE mode. Matches broker order IDs against our DB
    pending orders and confirms fills.
    """
    import asyncio
    from app.broker.angel_client import angel
    from app.database import async_session
    from app.pipeline import db_persistence as db

    try:
        order_book = await asyncio.wait_for(
            asyncio.to_thread(angel.get_order_book),
            timeout=15,
        )
    except asyncio.TimeoutError:
        logger.warning("Order book fetch timed out (15s)")
        return
    except Exception as e:
        logger.debug("Order book fetch failed: {}", e)
        return

    if not order_book or not isinstance(order_book, dict):
        return

    orders = order_book.get("data", [])
    if not isinstance(orders, list):
        return

    # Build lookup: broker_order_id -> broker status
    broker_fills = {}
    for o in orders:
        oid = str(o.get("orderid", ""))
        status = o.get("orderstatus", "").upper()
        filled_qty = int(o.get("filledshares", 0) or 0)
        avg_price = float(o.get("averageprice", 0) or 0)

        if oid and status in ("COMPLETE", "FILLED", "REJECTED", "CANCELLED"):
            broker_fills[oid] = {
                "status": "COMPLETE" if status in ("COMPLETE", "FILLED") else status,
                "filled_price": avg_price,
                "filled_quantity": filled_qty,
            }
        elif oid and status == "OPEN" and filled_qty > 0:
            # Partial fill — order still open but some shares filled
            broker_fills[oid] = {
                "status": "PARTIAL",
                "filled_price": avg_price,
                "filled_quantity": filled_qty,
            }

    if not broker_fills:
        return

    # Update our pending orders
    try:
        async with async_session() as session:
            pending = await db.load_pending_orders(session)
            for order in pending:
                fill = broker_fills.get(order.order_id)
                if not fill:
                    continue

                if fill["status"] == "COMPLETE":
                    await db.update_order_fill(
                        session, order.id,
                        filled_price=fill["filled_price"],
                        filled_quantity=fill["filled_quantity"],
                        status="COMPLETE",
                    )
                    logger.info(
                        "[LIVE] Order {} filled @ {} qty={}",
                        order.order_id, fill["filled_price"], fill["filled_quantity"],
                    )
                    # Confirm fill with executor
                    sym = order.symbol
                    for key, sess in pipeline_manager._sessions.items():
                        if sess.symbol == sym:
                            sess.executor.confirm_entry_fill(sym, fill["filled_price"], fill["filled_quantity"])
                            break
                    # Broadcast fill event to frontend
                    await broadcast_pipeline_event({
                        "type": "order_filled",
                        "order_id": order.order_id,
                        "symbol": order.symbol,
                        "filled_price": fill["filled_price"],
                        "filled_quantity": fill["filled_quantity"],
                    })

                elif fill["status"] == "PARTIAL":
                    # Update with partial fill info but keep PENDING
                    await db.update_order_fill(
                        session, order.id,
                        filled_price=fill["filled_price"],
                        filled_quantity=fill["filled_quantity"],
                        status="PENDING",  # Keep pending until fully filled
                    )
                    logger.info(
                        "[LIVE] Order {} PARTIAL fill: {} of {} @ {}",
                        order.order_id, fill["filled_quantity"], order.quantity, fill["filled_price"],
                    )
                    await broadcast_pipeline_event({
                        "type": "order_partial_fill",
                        "order_id": order.order_id,
                        "symbol": order.symbol,
                        "filled_price": fill["filled_price"],
                        "filled_quantity": fill["filled_quantity"],
                        "total_quantity": order.quantity,
                    })

                elif fill["status"] in ("REJECTED", "CANCELLED"):
                    await db.update_order_fill(
                        session, order.id,
                        status=fill["status"],
                    )
                    logger.warning(
                        "[LIVE] Order {} {}: {}",
                        order.order_id, fill["status"], order.symbol,
                    )
                    await broadcast_pipeline_event({
                        "type": "order_rejected",
                        "order_id": order.order_id,
                        "symbol": order.symbol,
                        "status": fill["status"],
                    })
                    # Notification
                    try:
                        from app.notifications.telegram import notify_order_rejected
                        await notify_order_rejected(
                            symbol=order.symbol,
                            direction=order.direction,
                            quantity=order.quantity,
                            reason=f"Broker {fill['status']}: order {order.order_id}",
                            mode="LIVE",
                        )
                    except Exception:
                        pass
    except Exception as e:
        logger.debug("Order fill update failed: {}", e)


def _ensure_heartbeat():
    """Start heartbeat task if not already running."""
    global _heartbeat_task
    if _heartbeat_task is None or _heartbeat_task.done():
        _heartbeat_task = asyncio.create_task(_heartbeat_loop())


async def broadcast_pipeline_event(event: dict):
    """Broadcast a structured pipeline event to all connected pipeline clients."""
    if not _pipeline_clients:
        return

    message = json.dumps(event, default=str)
    disconnected = []
    for ws in _pipeline_clients:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)

    for ws in disconnected:
        _pipeline_clients.remove(ws)


async def broadcast_user_event(user_id: int, event: dict):
    """Send a private event to a specific user's WebSocket connections only."""
    connections = _user_connections.get(user_id, [])
    if not connections:
        return

    message = json.dumps(event, default=str)
    disconnected = []
    for ws in connections:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        connections.remove(ws)


@router.websocket("/ws/pipeline")
async def pipeline_websocket(websocket: WebSocket):
    """WebSocket endpoint for structured pipeline events.

    Supports optional JWT auth via ?token= query param for multi-user.
    Unauthenticated connections still work (backward compat) but get all events.

    Event types: candle, indicators, signal, order, pipeline_status,
                 running_bar, trade_alert, heartbeat
    """
    # Authenticate if token provided (optional for backward compat)
    user_id = None
    try:
        from app.middleware.auth import get_ws_user
        user = await get_ws_user(websocket)
        if user:
            user_id = user.id
    except Exception:
        pass

    await websocket.accept()
    _pipeline_clients.append(websocket)

    # Register per-user connection
    if user_id:
        _user_connections.setdefault(user_id, []).append(websocket)
        _ws_user_map[id(websocket)] = user_id

    _ensure_heartbeat()
    logger.info("Pipeline WS client connected (user={}, total: {})",
                user_id or "anon", len(_pipeline_clients))

    try:
        # Send current pipeline status on connect
        from app.pipeline import pipeline_manager
        status = await pipeline_manager.get_status()

        # Also include broker/feed status
        try:
            from app.broker.websocket_feed import market_feed
            status["feed_connected"] = market_feed.is_connected
            status["feed_last_data_age"] = round(market_feed.last_data_age, 1)
        except Exception:
            status["feed_connected"] = False

        await websocket.send_text(json.dumps({
            "type": "pipeline_status",
            **status,
        }, default=str))

        # Keep connection alive and handle client messages
        while True:
            msg = await websocket.receive_text()
            try:
                request = json.loads(msg)
                action = request.get("action")

                if action == "start_tracking":
                    symbol = request.get("symbol", "RELIANCE")
                    exchange = request.get("exchange", "NSE")
                    try:
                        await pipeline_manager.start_tracking(symbol, exchange)
                        # Also subscribe on feed
                        try:
                            from app.broker.websocket_feed import market_feed
                            from app.broker.instruments import lookup_token, download_scrip_master
                            scrip_df = await download_scrip_master()
                            token = lookup_token(scrip_df, symbol, exchange)
                            if token and market_feed.is_connected:
                                market_feed.subscribe([token], exchange)
                                logger.info("Feed subscribed: {}:{} token={}", symbol, exchange, token)
                        except Exception as e:
                            logger.warning("Feed subscribe failed: {}", e)
                    except Exception as e:
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "message": str(e),
                        }))

                elif action == "stop_tracking":
                    symbol = request.get("symbol")
                    exchange = request.get("exchange", "NSE")
                    if symbol:
                        await pipeline_manager.stop_tracking(symbol, exchange)

                elif action == "backfill":
                    # Client requests candles missed during disconnect
                    symbol = request.get("symbol")
                    exchange = request.get("exchange", "NSE")
                    since = request.get("since")
                    if symbol and since:
                        try:
                            backfill_data = await pipeline_manager.get_backfill(
                                symbol, exchange, since
                            )
                            await websocket.send_text(json.dumps({
                                "type": "backfill_response",
                                "symbol": symbol,
                                "candles": backfill_data,
                            }, default=str))
                        except Exception as e:
                            logger.warning("Backfill failed: {}", e)

                elif action == "get_status":
                    status = await pipeline_manager.get_status()
                    await websocket.send_text(json.dumps({
                        "type": "pipeline_status",
                        **status,
                    }, default=str))

            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        pass
    finally:
        if websocket in _pipeline_clients:
            _pipeline_clients.remove(websocket)
        # Clean up per-user tracking
        ws_id = id(websocket)
        uid = _ws_user_map.pop(ws_id, None)
        if uid and uid in _user_connections:
            conns = _user_connections[uid]
            if websocket in conns:
                conns.remove(websocket)
            if not conns:
                del _user_connections[uid]
        logger.info("Pipeline WS client disconnected (user={}, total: {})",
                    uid or "anon", len(_pipeline_clients))
