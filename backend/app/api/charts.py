"""Chart data API endpoints — candles and indicators.

When live broker data is unavailable (session expired, offline mode),
automatically falls back to realistic demo data so the dashboard
always shows functional charts.
"""

import asyncio
from datetime import datetime, timedelta
from fastapi import APIRouter, Query
from loguru import logger

from app.broker.instruments import lookup_token, download_scrip_master
from app.api.demo_data import get_demo_candles, get_demo_weekly_candles

router = APIRouter(prefix="/api/charts", tags=["charts"])

# ── Simple in-memory cache for candle data (avoids hammering Angel One) ──
_candle_cache: dict[str, tuple[float, any]] = {}  # key -> (timestamp, df)
CACHE_TTL = 60  # seconds

# ── Singleflight locks: prevent duplicate concurrent broker calls for same data ──
_fetch_locks: dict[str, asyncio.Lock] = {}

# Track broker availability — skip live calls when known offline
_broker_offline = False
_broker_fail_count = 0
_MAX_FAILS_BEFORE_SKIP = 5
_broker_offline_since: float = 0  # timestamp when marked offline

import time as _time

OFFLINE_RESET_SECONDS = 60  # Auto-retry broker after 60s


def _check_offline_reset():
    """Auto-reset offline flag after timeout so broker gets retried."""
    global _broker_offline, _broker_fail_count, _broker_offline_since
    if _broker_offline and (_time.time() - _broker_offline_since) > OFFLINE_RESET_SECONDS:
        logger.info("Resetting broker offline flag after {}s", OFFLINE_RESET_SECONDS)
        _broker_offline = False
        _broker_fail_count = 0


def reset_broker_offline():
    """Manually reset broker offline state."""
    global _broker_offline, _broker_fail_count, _broker_offline_since
    _broker_offline = False
    _broker_fail_count = 0
    _broker_offline_since = 0


def _fetch_candles_sync(token, exchange, interval, from_date):
    """Synchronous broker fetch (runs in thread pool)."""
    try:
        from app.broker.historical import fetch_historical_candles
        df = fetch_historical_candles(
            symbol_token=token,
            exchange=exchange,
            interval=interval,
            from_date=from_date,
        )
        return df
    except RuntimeError as e:
        logger.warning("Historical client not available: {}", e)
        return None
    except Exception as e:
        logger.error("Candle fetch failed: {}", e)
        return None


async def fetch_candles_async(token, exchange, interval, from_date):
    """Async candle fetch with cache + singleflight (no duplicate broker calls).

    If another request for the same cache key is already in-flight,
    this waits for it instead of making a duplicate broker call.
    """
    cache_key = f"{exchange}:{token}:{interval}"
    now = _time.time()

    # Fast path: return cached result without lock
    if cache_key in _candle_cache:
        ts, cached_df = _candle_cache[cache_key]
        if (now - ts) < CACHE_TTL and cached_df is not None and not cached_df.empty:
            logger.debug("Serving cached candles for {} (age={}s)", cache_key, int(now - ts))
            return cached_df

    # Singleflight: only one broker call per cache key at a time
    if cache_key not in _fetch_locks:
        _fetch_locks[cache_key] = asyncio.Lock()

    async with _fetch_locks[cache_key]:
        # Re-check cache inside lock (another request may have filled it)
        now = _time.time()
        if cache_key in _candle_cache:
            ts, cached_df = _candle_cache[cache_key]
            if (now - ts) < CACHE_TTL and cached_df is not None and not cached_df.empty:
                logger.debug("Singleflight cache hit for {}", cache_key)
                return cached_df

        # Actually fetch from broker in thread pool
        df = await asyncio.to_thread(_fetch_candles_sync, token, exchange, interval, from_date)
        if df is not None and not df.empty:
            _candle_cache[cache_key] = (_time.time(), df)
        return df


def _df_to_candles(df):
    """Convert DataFrame to serializable candle list."""
    candles = df.to_dict(orient="records")
    for c in candles:
        if hasattr(c["timestamp"], "isoformat"):
            c["timestamp"] = c["timestamp"].isoformat()
        else:
            c["timestamp"] = str(c["timestamp"])
    return candles


@router.get("/candles")
async def get_candles(
    symbol: str = Query(..., description="Trading symbol (e.g., RELIANCE)"),
    exchange: str = Query("NSE", description="Exchange: NSE, NFO, BSE, MCX"),
    interval: str = Query("1d", description="Interval: 1m, 5m, 15m, 30m, 1h, 1d"),
    days: int = Query(365, description="Number of days of history"),
):
    """Fetch OHLCV candle data for charting. Falls back to demo data if broker unavailable."""
    global _broker_offline, _broker_fail_count, _broker_offline_since

    # Auto-reset offline flag after timeout
    _check_offline_reset()

    # Try live data first (skip if broker known offline)
    if not _broker_offline:
        try:
            scrip_df = await download_scrip_master()
            token = lookup_token(scrip_df, symbol, exchange)

            if token:
                df = await fetch_candles_async(token, exchange, interval, datetime.now() - timedelta(days=days))
                if df is not None and not df.empty:
                    _broker_fail_count = 0  # Reset on success
                    candles = _df_to_candles(df)
                    return {
                        "data": candles,
                        "symbol": symbol,
                        "exchange": exchange,
                        "interval": interval,
                        "count": len(candles),
                        "source": "live",
                    }
                else:
                    _broker_fail_count += 1
                    if _broker_fail_count >= _MAX_FAILS_BEFORE_SKIP:
                        _broker_offline = True
                        _broker_offline_since = _time.time()
                        logger.warning("Broker marked offline after {} consecutive failures", _broker_fail_count)
        except Exception as e:
            _broker_fail_count += 1
            if _broker_fail_count >= _MAX_FAILS_BEFORE_SKIP:
                _broker_offline = True
                _broker_offline_since = _time.time()
            logger.warning("Live data unavailable for {}: {}", symbol, e)

    # Fallback to demo data
    logger.info("Serving demo data for {}:{} interval={}", symbol, exchange, interval)
    demo_df = get_demo_candles(symbol, exchange, interval, days)

    if demo_df is None or demo_df.empty:
        return {
            "data": [], "symbol": symbol, "exchange": exchange,
            "interval": interval, "count": 0,
            "error": "No data available",
        }

    candles = _df_to_candles(demo_df)
    return {
        "data": candles,
        "symbol": symbol,
        "exchange": exchange,
        "interval": interval,
        "count": len(candles),
        "source": "demo",
    }


@router.post("/reset-broker")
async def reset_broker_status():
    """Reset broker offline flag to retry live data."""
    reset_broker_offline()
    return {"status": True, "message": "Broker status reset, will retry live data"}


@router.get("/weekly")
async def get_weekly_candles(
    symbol: str = Query(...),
    exchange: str = Query("NSE"),
    days: int = Query(730),
):
    """Fetch weekly OHLCV data. Falls back to demo data if broker unavailable."""
    global _broker_offline, _broker_fail_count, _broker_offline_since

    _check_offline_reset()

    # Try live data first (skip if broker known offline)
    if not _broker_offline:
        try:
            scrip_df = await download_scrip_master()
            token = lookup_token(scrip_df, symbol, exchange)

            if token:
                from app.broker.historical import fetch_weekly_candles
                df = await asyncio.to_thread(fetch_weekly_candles, token, exchange, days)
                if not df.empty:
                    _broker_fail_count = 0
                    candles = _df_to_candles(df)
                    return {
                        "data": candles, "symbol": symbol,
                        "interval": "1w", "count": len(candles),
                        "source": "live",
                    }
                else:
                    _broker_fail_count += 1
                    if _broker_fail_count >= _MAX_FAILS_BEFORE_SKIP:
                        _broker_offline = True
                        _broker_offline_since = _time.time()
        except Exception as e:
            _broker_fail_count += 1
            if _broker_fail_count >= _MAX_FAILS_BEFORE_SKIP:
                _broker_offline = True
                _broker_offline_since = _time.time()
            logger.warning("Live weekly data unavailable for {}: {}", symbol, e)

    # Fallback to demo data
    logger.info("Serving demo weekly data for {}:{}", symbol, exchange)
    demo_df = get_demo_weekly_candles(symbol, exchange, days)

    if demo_df is None or demo_df.empty:
        return {
            "data": [], "symbol": symbol,
            "interval": "1w", "count": 0,
            "error": "No data available",
        }

    candles = _df_to_candles(demo_df)
    return {
        "data": candles, "symbol": symbol,
        "interval": "1w", "count": len(candles),
        "source": "demo",
    }
