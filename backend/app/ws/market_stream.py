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
_tick_queue: list[dict] = []
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

                        # Check stop losses (throttled: every 2s per session)
                        if current_price > 0:
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

            msg = json.dumps({
                "type": "heartbeat",
                "ts": now,
                "feed_connected": feed_connected,
                "feed_last_data_age": round(feed_age, 1),
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

        await asyncio.sleep(0.05)  # 50ms poll cycle


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


@router.websocket("/ws/pipeline")
async def pipeline_websocket(websocket: WebSocket):
    """WebSocket endpoint for structured pipeline events.

    Event types: candle, indicators, signal, order, pipeline_status,
                 running_bar, trade_alert, heartbeat
    """
    await websocket.accept()
    _pipeline_clients.append(websocket)
    _ensure_heartbeat()
    logger.info("Pipeline WS client connected (total: {})", len(_pipeline_clients))

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
        logger.info("Pipeline WS client disconnected (total: {})", len(_pipeline_clients))
