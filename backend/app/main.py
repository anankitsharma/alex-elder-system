"""FastAPI application entry point."""

import asyncio
import time
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
from app.ws.market_stream import on_tick_received, broadcast_pipeline_event
from app.pipeline import pipeline_manager

# Import routers
from app.api.charts import router as charts_router
from app.api.trading import router as trading_router
from app.api.scanner import router as scanner_router
from app.api.indicators import router as indicators_router
from app.api.strategy import router as strategy_router
from app.api.settings import router as settings_router
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

    # Wire pipeline manager broadcast
    pipeline_manager.set_broadcast(broadcast_pipeline_event)

    # Login to Angel One APIs (non-blocking — run in thread pool)
    loop = asyncio.get_event_loop()
    try:
        success = await asyncio.wait_for(
            loop.run_in_executor(_executor, angel.login_all),
            timeout=30,
        )
        if success:
            logger.info("All Angel One API sessions active")
            market_feed.add_callback(on_tick_received)
            market_feed.add_callback(pipeline_manager.on_tick)
            # Start WebSocket feed in background thread (connect() is blocking)
            import threading
            feed_thread = threading.Thread(target=market_feed.connect, daemon=True)
            feed_thread.start()
            logger.info("Market feed WebSocket starting in background thread")
        else:
            logger.warning("Some Angel One logins failed — running in offline mode")
    except asyncio.TimeoutError:
        logger.warning("Angel One login timed out (30s) — running in offline mode")
    except Exception as e:
        logger.error("Angel One login error: {} — running in offline mode", e)

    logger.info("Elder Trading System ready at http://localhost:8000")
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

    return {
        "status": "ok",
        "trading_mode": settings.trading_mode,
        "feed_connected": feed_connected,
        "feed_last_data_age": feed_age,
        "active_sessions": active_sessions,
        "broker_online": feed_connected or feed_age >= 0,
        "risk_per_trade": f"{settings.max_risk_per_trade_pct}%",
        "portfolio_risk_limit": f"{settings.max_portfolio_risk_pct}%",
        "min_signal_score": settings.min_signal_score,
    }
