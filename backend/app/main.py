"""FastAPI application entry point."""

import asyncio
import sys
import time

# Windows: use SelectorEventLoop for thread-safe coroutine scheduling
# (ProactorEventLoop's call_soon_threadsafe raises [Errno 22] from feed threads)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.database import init_db
from app.broker.angel_client import angel
from app.broker.websocket_feed import market_feed
from app.ws.market_stream import on_tick_received, broadcast_pipeline_event, set_main_loop, _ensure_heartbeat
from app.pipeline import pipeline_manager

# Import routers
from app.api.charts import router as charts_router
from app.api.trading import router as trading_router
from app.api.scanner import router as scanner_router
from app.api.indicators import router as indicators_router
from app.api.strategy import router as strategy_router
from app.api.settings import router as settings_router
from app.api.auth import router as auth_router
from app.api.admin import router as admin_router
from app.ws.market_stream import router as ws_router

_executor = ThreadPoolExecutor(max_workers=2)


# ── Rate Limiting Middleware ────────────────────────────────────
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiter per client IP."""

    def __init__(self, app, max_requests: int = 60, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        # Only rate-limit mutation endpoints (POST, DELETE) — reads are safe
        if request.method in ("GET", "OPTIONS", "HEAD"):
            return await call_next(request)
        # Skip rate limiting for health, root, session, and WebSocket
        skip_paths = ("/", "/api/health", "/api/trading/session/refresh", "/api/trading/paper/reset")
        if request.url.path in skip_paths or request.url.path.startswith("/ws"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        cutoff = now - self.window

        # Prune old entries
        self._hits[client_ip] = [t for t in self._hits[client_ip] if t > cutoff]

        # Stricter limit for order endpoints in LIVE mode
        limit = self.max_requests
        if "/order" in request.url.path and request.method == "POST":
            from app.config import settings as _cfg
            if _cfg.trading_mode == "LIVE":
                limit = _cfg.max_orders_per_minute

        if len(self._hits[client_ip]) >= limit:
            logger.warning("Rate limit exceeded for {}: {} requests/{}s", client_ip, limit, self.window)
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
            )

        self._hits[client_ip].append(now)
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    # Startup
    logger.info("Starting Elder Trading System v0.3.0...")
    logger.info("Trading mode: {}", settings.trading_mode)

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Seed roles and permissions (idempotent — skips if already exist)
    from app.seed import seed_roles_and_permissions
    await seed_roles_and_permissions()

    # Store main event loop for thread-safe scheduling from feed callbacks
    set_main_loop(asyncio.get_running_loop())

    # Wire pipeline manager broadcast
    pipeline_manager.set_broadcast(broadcast_pipeline_event)

    # ── ALWAYS start heartbeat + pipeline (broker-independent) ──
    # These work with demo data even when broker is offline
    market_feed.add_callback(on_tick_received)
    _ensure_heartbeat()

    # ── Broker connection (background, with retry) ──
    # Broker login is attempted in the background. If it fails, the system
    # runs in demo/offline mode. Pipelines start regardless.
    _broker_state = {"status": "CONNECTING", "attempts": 0, "last_error": ""}

    async def _connect_broker():
        """Attempt broker login with exponential backoff. Non-blocking."""
        import threading
        loop = asyncio.get_event_loop()
        max_attempts = 5
        for attempt in range(1, max_attempts + 1):
            _broker_state["attempts"] = attempt
            _broker_state["status"] = "CONNECTING"
            try:
                success = await asyncio.wait_for(
                    loop.run_in_executor(_executor, angel.login_all),
                    timeout=30,
                )
                if success:
                    _broker_state["status"] = "CONNECTED"
                    _broker_state["last_error"] = ""
                    logger.info("Broker connected (attempt {})", attempt)
                    # Start live feed
                    feed_thread = threading.Thread(target=market_feed.connect, daemon=True)
                    feed_thread.start()
                    logger.info("Market feed WebSocket starting")
                    # Subscribe tracked instruments to feed
                    await asyncio.sleep(3)
                    try:
                        from app.broker.instruments import download_scrip_master, lookup_token
                        scrip_df = await download_scrip_master()
                        for sym, exch in TRACKED_INSTRUMENTS:
                            token = lookup_token(scrip_df, sym, exch)
                            if token:
                                market_feed.subscribe([token], exch)
                    except Exception:
                        pass
                    return  # Success — done
                else:
                    _broker_state["last_error"] = "Login returned False"
            except asyncio.TimeoutError:
                _broker_state["last_error"] = "Connection timeout (30s)"
            except Exception as e:
                _broker_state["last_error"] = str(e)

            _broker_state["status"] = "RECONNECTING"
            delay = min(10 * (2 ** (attempt - 1)), 120)  # 10s, 20s, 40s, 80s, 120s
            logger.warning(
                "Broker connect attempt {}/{} failed: {} — retrying in {}s",
                attempt, max_attempts, _broker_state["last_error"], delay,
            )
            await asyncio.sleep(delay)

        _broker_state["status"] = "OFFLINE"
        logger.warning("Broker OFFLINE after {} attempts — running in demo mode", max_attempts)

    # ── Auto-start all tracked instruments (always, regardless of broker) ──
    async def _auto_start_pipeline():
        """Start all tracked instruments. Uses demo data if broker is offline."""
        await asyncio.sleep(2)  # Brief wait for DB init
        from app.config import TRACKED_INSTRUMENTS
        started = 0
        for sym, exch in TRACKED_INSTRUMENTS:
            try:
                await pipeline_manager.start_tracking(sym, exch)
                started += 1
            except Exception as e:
                logger.warning("Pipeline start failed for {}:{}: {}", sym, exch, e)
            await asyncio.sleep(1)  # Rate limit
        logger.info("Auto-started {}/{} pipelines (broker: {})",
                    started, len(TRACKED_INSTRUMENTS), _broker_state["status"])

    # Launch both in parallel — pipelines start immediately, broker retries in background
    asyncio.create_task(_auto_start_pipeline())
    asyncio.create_task(_connect_broker())

    # Expose broker state for API/frontend
    app.state.broker_state = _broker_state

    logger.info("Elder Trading System ready at http://localhost:8000")

    # Telegram startup notification
    try:
        from app.notifications.telegram import notify_system_start
        await notify_system_start()
    except Exception:
        pass

    yield

    # Shutdown — graceful
    logger.info("Shutting down Elder Trading System...")
    await pipeline_manager.shutdown()
    market_feed.disconnect()
    _executor.shutdown(wait=True)  # Wait for in-flight broker operations
    logger.info("Shutdown complete")


app = FastAPI(
    title="Elder Trading System",
    description="Alexander Elder's trading methodology for Indian markets (NSE/BSE/MCX)",
    version="0.3.0",
    lifespan=lifespan,
)

# Rate limiting (60 requests/min general, 10 orders/min)
app.add_middleware(RateLimitMiddleware, max_requests=60, window_seconds=60)

# CORS — allow frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", "http://127.0.0.1:3000",
        "http://localhost:3001", "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# Register routes
app.include_router(charts_router)
app.include_router(trading_router)
app.include_router(scanner_router)
app.include_router(indicators_router)
app.include_router(strategy_router)
app.include_router(settings_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(ws_router)


@app.get("/")
async def root():
    return {
        "name": "Elder Trading System",
        "version": "0.3.0",
        "mode": settings.trading_mode,
        "status": "running",
    }


@app.get("/api/health")
async def health():
    # Broker/feed status
    try:
        feed_connected = market_feed.is_connected
        feed_age = round(market_feed.last_data_age, 1)
    except Exception:
        feed_connected = False
        feed_age = -1

    # Pipeline status
    try:
        pipeline_status = await pipeline_manager.get_status()
        active_sessions = pipeline_status.get("active_sessions", 0)
    except Exception:
        active_sessions = 0

    # Broker connection state
    broker = getattr(app.state, "broker_state", {})

    return {
        "status": "ok",
        "trading_mode": settings.trading_mode,
        "feed_connected": feed_connected,
        "feed_last_data_age": feed_age,
        "active_sessions": active_sessions,
        "broker_status": broker.get("status", "UNKNOWN"),
        "broker_attempts": broker.get("attempts", 0),
        "broker_error": broker.get("last_error", ""),
        "broker_online": broker.get("status") == "CONNECTED",
        "risk_per_trade": f"{settings.max_risk_per_trade_pct}%",
        "portfolio_risk_limit": f"{settings.max_portfolio_risk_pct}%",
        "min_signal_score": settings.min_signal_score,
    }


@app.get("/api/broker/status")
async def broker_status():
    """Broker connection status — shows state, attempts, errors."""
    broker = getattr(app.state, "broker_state", {})
    try:
        feed_connected = market_feed.is_connected
        feed_age = round(market_feed.last_data_age, 1)
    except Exception:
        feed_connected = False
        feed_age = -1
    return {
        "status": broker.get("status", "UNKNOWN"),
        "attempts": broker.get("attempts", 0),
        "last_error": broker.get("last_error", ""),
        "feed_connected": feed_connected,
        "feed_last_data_age": feed_age,
    }


@app.post("/api/broker/retry")
async def broker_retry():
    """Manually trigger broker reconnection attempt."""
    broker = getattr(app.state, "broker_state", {})
    if broker.get("status") == "CONNECTED":
        return {"status": "already_connected"}

    broker["status"] = "CONNECTING"
    broker["attempts"] = 0

    # Re-run broker connection in background
    import threading
    loop = asyncio.get_event_loop()

    async def _retry():
        try:
            success = await asyncio.wait_for(
                loop.run_in_executor(_executor, angel.login_all),
                timeout=30,
            )
            if success:
                broker["status"] = "CONNECTED"
                broker["last_error"] = ""
                logger.info("Broker reconnected via manual retry")
                # Start feed if not running
                if not market_feed.is_connected:
                    feed_thread = threading.Thread(target=market_feed.connect, daemon=True)
                    feed_thread.start()
                return
        except Exception as e:
            broker["last_error"] = str(e)

        broker["status"] = "OFFLINE"
        logger.warning("Manual broker retry failed: {}", broker["last_error"])

    asyncio.create_task(_retry())
    return {"status": "retrying", "message": "Broker reconnection started in background"}
