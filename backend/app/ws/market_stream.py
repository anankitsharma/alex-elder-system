"""WebSocket endpoints for live market data and pipeline events."""

import asyncio
import json
import time as _time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

router = APIRouter()

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

    This runs in SmartWebSocketV2's thread, so we schedule the async broadcast
    on the main event loop.
    """
    if isinstance(tick_data, dict):
        data = tick_data
    else:
        # SmartWebSocketV2 may send binary data; parse as needed
        try:
            data = json.loads(tick_data) if isinstance(tick_data, str) else tick_data
        except (json.JSONDecodeError, TypeError):
            return

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(broadcast_tick(data))
    except RuntimeError:
        pass


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
    """Send heartbeat to all pipeline clients every HEARTBEAT_INTERVAL seconds."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        if not _pipeline_clients:
            continue
        try:
            from app.broker.websocket_feed import market_feed
            feed_connected = market_feed.is_connected
            feed_age = market_feed.last_data_age
        except Exception:
            feed_connected = False
            feed_age = -1

        msg = json.dumps({
            "type": "heartbeat",
            "ts": _time.time(),
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
