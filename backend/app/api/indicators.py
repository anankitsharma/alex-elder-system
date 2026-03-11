"""Indicator computation API — overlays for chart data.

Computes Elder indicators (EMA, MACD, Force Index, Impulse, SafeZone)
on candle data and returns results aligned per-bar for frontend rendering.
"""

import asyncio
import time as _time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from fastapi import APIRouter, Query
from loguru import logger

from app.api.demo_data import get_demo_candles
from app.broker.instruments import lookup_token, download_scrip_master
try:
    from app.indicators.timeframe_config import should_compute_indicator
except ImportError:
    from backend.app.indicators.timeframe_config import should_compute_indicator

router = APIRouter(prefix="/api/indicators", tags=["indicators"])

# ── Indicator result cache (avoids recomputing for duplicate/Strict Mode requests) ──
_indicator_cache: dict[str, tuple[float, dict]] = {}  # key -> (timestamp, result)
_INDICATOR_CACHE_TTL = 30  # seconds
_indicator_locks: dict[str, asyncio.Lock] = {}


async def _get_candle_df(symbol: str, exchange: str, interval: str, days: int) -> pd.DataFrame | None:
    """Get candle data from broker or demo, return as DataFrame."""
    # Try live data first
    try:
        from app.api.charts import _broker_offline, fetch_candles_async

        if not _broker_offline:
            scrip_df = await download_scrip_master()
            token = lookup_token(scrip_df, symbol, exchange)
            if token:
                df = await fetch_candles_async(token, exchange, interval, datetime.now() - timedelta(days=days))
                if df is not None and not df.empty:
                    return df
    except Exception:
        pass

    # Fallback to demo data
    return get_demo_candles(symbol, exchange, interval, days)


def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure DataFrame has 'datetime' column and standard OHLCV columns."""
    if df is None or df.empty:
        return pd.DataFrame()

    # Rename 'timestamp' to 'datetime' if needed
    if "timestamp" in df.columns and "datetime" not in df.columns:
        df = df.rename(columns={"timestamp": "datetime"})

    # Ensure datetime column exists
    if "datetime" not in df.columns:
        if df.index.name == "datetime" or df.index.name == "timestamp":
            df = df.reset_index()
        else:
            df["datetime"] = pd.date_range(end=datetime.now(), periods=len(df), freq="D")

    return df


def _compute_indicators_sync(df: pd.DataFrame, symbol: str, interval: str, screen: int | None) -> dict:
    """Compute all indicators synchronously (runs in thread pool).

    This is CPU-bound work — running in a thread prevents blocking the event loop.
    """
    n = len(df)

    result = {
        "timestamps": [],
        "ema13": [],
        "ema22": [],
        "macd_line": [],
        "macd_signal": [],
        "macd_histogram": [],
        "force_index": [],
        "force_index_2": [],
        "impulse_color": [],
        "impulse_signal": [],
        "safezone_long": [],
        "safezone_short": [],
        "elder_ray_bull": [],
        "elder_ray_bear": [],
        "value_zone_fast": [],
        "value_zone_slow": [],
        "auto_envelope_upper": [],
        "auto_envelope_lower": [],
        "auto_envelope_ema": [],
        "thermometer_raw": [],
        "thermometer_smoothed": [],
        "macd_divergence_signal": [],
    }

    # Timestamps
    for ts in df["datetime"]:
        if hasattr(ts, "isoformat"):
            result["timestamps"].append(ts.isoformat())
        else:
            result["timestamps"].append(str(ts))

    # EMA-13
    if should_compute_indicator('ema13', screen):
        try:
            from app.indicators.ema import EMAEnhanced
            ema13 = EMAEnhanced(symbol, interval, {"period": 13, "source": "close", "ma_type": "None"})
            ema13_df = ema13.calculate(df)
            ema13_vals = ema13_df["ema"].values
            pad = n - len(ema13_vals)
            result["ema13"] = [None] * pad + [round(float(v), 2) if not np.isnan(v) else None for v in ema13_vals]
        except Exception as e:
            logger.warning("EMA-13 calc failed: {}", e)
            result["ema13"] = [None] * n
    else:
        result["ema13"] = [None] * n

    # EMA-22
    if should_compute_indicator('ema22', screen):
        try:
            from app.indicators.ema import EMAEnhanced
            ema22 = EMAEnhanced(symbol, interval, {"period": 22, "source": "close", "ma_type": "None"})
            ema22_df = ema22.calculate(df)
            ema22_vals = ema22_df["ema"].values
            pad = n - len(ema22_vals)
            result["ema22"] = [None] * pad + [round(float(v), 2) if not np.isnan(v) else None for v in ema22_vals]
        except Exception as e:
            logger.warning("EMA-22 calc failed: {}", e)
            result["ema22"] = [None] * n
    else:
        result["ema22"] = [None] * n

    # MACD
    if should_compute_indicator('macd', screen):
        try:
            from app.indicators.macd import MACDEnhanced
            macd = MACDEnhanced(symbol, interval, {
                "fast_length": 12, "slow_length": 26, "signal_length": 9,
                "source": "close", "oscillator_ma_type": "EMA", "signal_ma_type": "EMA",
            })
            macd_df = macd.calculate(df)
            macd_vals = macd_df["macd_line"].values
            signal_vals = macd_df["signal_line"].values
            hist_vals = macd_df["histogram"].values
            pad = n - len(macd_vals)
            result["macd_line"] = [None] * pad + [round(float(v), 2) if not np.isnan(v) else None for v in macd_vals]
            result["macd_signal"] = [None] * pad + [round(float(v), 2) if not np.isnan(v) else None for v in signal_vals]
            result["macd_histogram"] = [None] * pad + [round(float(v), 2) if not np.isnan(v) else None for v in hist_vals]
        except Exception as e:
            logger.warning("MACD calc failed: {}", e)
            result["macd_line"] = [None] * n
            result["macd_signal"] = [None] * n
            result["macd_histogram"] = [None] * n
    else:
        result["macd_line"] = [None] * n
        result["macd_signal"] = [None] * n
        result["macd_histogram"] = [None] * n

    # Force Index (13-period)
    if should_compute_indicator('force_index_13', screen):
        try:
            from app.indicators.force_index import ForceIndexEnhanced
            fi = ForceIndexEnhanced(symbol, interval, {"length": 13, "source": "close"})
            fi_df = fi.calculate(df)
            fi_vals = fi_df["efi"].values
            pad = n - len(fi_vals)
            result["force_index"] = [None] * pad + [round(float(v), 2) if not np.isnan(v) else None for v in fi_vals]
        except Exception as e:
            logger.warning("Force Index 13 calc failed: {}", e)
            result["force_index"] = [None] * n
    else:
        result["force_index"] = [None] * n

    # Force Index (2-period) — Screen 2 entry timing
    if should_compute_indicator('force_index_2', screen):
        try:
            from app.indicators.force_index import ForceIndexEnhanced
            fi2 = ForceIndexEnhanced(symbol, interval, {"length": 2, "source": "close"})
            fi2_df = fi2.calculate(df)
            fi2_vals = fi2_df["efi"].values
            pad = n - len(fi2_vals)
            result["force_index_2"] = [None] * pad + [round(float(v), 2) if not np.isnan(v) else None for v in fi2_vals]
        except Exception as e:
            logger.warning("Force Index 2 calc failed: {}", e)
            result["force_index_2"] = [None] * n
    else:
        result["force_index_2"] = [None] * n

    # Elder Impulse System
    if should_compute_indicator('impulse', screen):
        try:
            from app.indicators.impulse import ElderImpulseEnhanced
            impulse = ElderImpulseEnhanced(symbol, interval, {
                "macd_fast_length": 12, "macd_slow_length": 26,
                "macd_signal_length": 9, "ema_length": 13,
                "source": "close",
                "bullish_color": "green", "bearish_color": "red", "neutral_color": "blue",
            })
            impulse_df = impulse.calculate(df)
            colors = impulse_df["impulse_color"].tolist()
            signals = impulse_df["impulse_signal"].tolist()
            pad = n - len(colors)
            result["impulse_color"] = [None] * pad + colors
            result["impulse_signal"] = [None] * pad + signals
        except Exception as e:
            logger.warning("Impulse calc failed: {}", e)
            result["impulse_color"] = [None] * n
            result["impulse_signal"] = [None] * n
    else:
        result["impulse_color"] = [None] * n
        result["impulse_signal"] = [None] * n

    # SafeZone V2 (support/resistance stops)
    if should_compute_indicator('safezone', screen):
        try:
            from app.indicators.safezone import SafeZoneV2
            sz = SafeZoneV2(symbol, interval, {
                "lookback_length": 22, "coefficient": 2.0, "progressive_mode": True,
            })
            sz_df = sz.calculate(df)
            long_vals = sz_df["longvs"].values
            short_vals = sz_df["shortvs"].values
            pad = n - len(long_vals)
            result["safezone_long"] = [None] * pad + [round(float(v), 2) if not np.isnan(v) else None for v in long_vals]
            result["safezone_short"] = [None] * pad + [round(float(v), 2) if not np.isnan(v) else None for v in short_vals]
        except Exception as e:
            logger.warning("SafeZone calc failed: {}", e)
            result["safezone_long"] = [None] * n
            result["safezone_short"] = [None] * n
    else:
        result["safezone_long"] = [None] * n
        result["safezone_short"] = [None] * n

    # Elder-Ray (Bull Power / Bear Power)
    if should_compute_indicator('elder_ray', screen):
        try:
            from app.indicators.elder_ray import ElderRay
            er = ElderRay(symbol, interval, {"period": 13})
            er_df = er.calculate(df)
            bull = er_df["bull_power"].values
            bear = er_df["bear_power"].values
            pad = n - len(bull)
            result["elder_ray_bull"] = [None] * pad + [round(float(v), 2) if not np.isnan(v) else None for v in bull]
            result["elder_ray_bear"] = [None] * pad + [round(float(v), 2) if not np.isnan(v) else None for v in bear]
        except Exception as e:
            logger.warning("Elder-Ray calc failed: {}", e)
            result["elder_ray_bull"] = [None] * n
            result["elder_ray_bear"] = [None] * n
    else:
        result["elder_ray_bull"] = [None] * n
        result["elder_ray_bear"] = [None] * n

    # Value Zone (EMA-13 / EMA-26 channel)
    if should_compute_indicator('value_zone', screen):
        try:
            from app.indicators.value_zone import ValueZone
            vz = ValueZone(symbol, interval, {"fast_period": 13, "slow_period": 26})
            vz_df = vz.calculate(df)
            fast_vals = vz_df["fast_ema"].values
            slow_vals = vz_df["slow_ema"].values
            pad = n - len(fast_vals)
            result["value_zone_fast"] = [None] * pad + [round(float(v), 2) if not np.isnan(v) else None for v in fast_vals]
            result["value_zone_slow"] = [None] * pad + [round(float(v), 2) if not np.isnan(v) else None for v in slow_vals]
        except Exception as e:
            logger.warning("Value Zone calc failed: {}", e)
            result["value_zone_fast"] = [None] * n
            result["value_zone_slow"] = [None] * n
    else:
        result["value_zone_fast"] = [None] * n
        result["value_zone_slow"] = [None] * n

    # AutoEnvelope (EMA-22 +/- 2.7 SD)
    if should_compute_indicator('auto_envelope', screen):
        try:
            from app.indicators.auto_envelope import AutoEnvelope
            ae = AutoEnvelope(symbol, interval, {"period": 22, "multiplier": 2.7, "lookback": 100})
            ae_df = ae.calculate(df)
            upper = ae_df["upper"].values
            lower = ae_df["lower"].values
            ema_ae = ae_df["ema"].values
            pad = n - len(upper)
            result["auto_envelope_upper"] = [None] * pad + [round(float(v), 2) if not np.isnan(v) else None for v in upper]
            result["auto_envelope_lower"] = [None] * pad + [round(float(v), 2) if not np.isnan(v) else None for v in lower]
            result["auto_envelope_ema"] = [None] * pad + [round(float(v), 2) if not np.isnan(v) else None for v in ema_ae]
        except Exception as e:
            logger.warning("AutoEnvelope calc failed: {}", e)
            result["auto_envelope_upper"] = [None] * n
            result["auto_envelope_lower"] = [None] * n
            result["auto_envelope_ema"] = [None] * n
    else:
        result["auto_envelope_upper"] = [None] * n
        result["auto_envelope_lower"] = [None] * n
        result["auto_envelope_ema"] = [None] * n

    # Elder Thermometer (volatility)
    if should_compute_indicator('elder_thermometer', screen):
        try:
            from app.indicators.elder_thermometer import ElderThermometer
            et = ElderThermometer(symbol, interval, {"period": 22})
            et_df = et.calculate(df)
            raw = et_df["raw"].values
            smoothed = et_df["smoothed"].values
            pad = n - len(raw)
            result["thermometer_raw"] = [None] * pad + [round(float(v), 4) if not np.isnan(v) else None for v in raw]
            result["thermometer_smoothed"] = [None] * pad + [round(float(v), 4) if not np.isnan(v) else None for v in smoothed]
        except Exception as e:
            logger.warning("Elder Thermometer calc failed: {}", e)
            result["thermometer_raw"] = [None] * n
            result["thermometer_smoothed"] = [None] * n
    else:
        result["thermometer_raw"] = [None] * n
        result["thermometer_smoothed"] = [None] * n

    # MACD-Histogram Divergence
    if should_compute_indicator('macd_divergence', screen):
        try:
            from app.indicators.macd_divergence import MACDDivergence
            md = MACDDivergence(symbol, interval, {
                "fast_length": 12, "slow_length": 26, "signal_length": 9,
            })
            md_df = md.calculate(df)
            div_signal = md_df["divergence_signal"].values
            pad = n - len(div_signal)
            result["macd_divergence_signal"] = [None] * pad + [float(v) for v in div_signal]
        except Exception as e:
            logger.warning("MACD Divergence calc failed: {}", e)
            result["macd_divergence_signal"] = [None] * n
    else:
        result["macd_divergence_signal"] = [None] * n

    return result


@router.get("/compute")
async def compute_indicators(
    symbol: str = Query(..., description="Trading symbol"),
    exchange: str = Query("NSE"),
    interval: str = Query("1d"),
    days: int = Query(365),
    screen: int = Query(None, description="Screen number (1/2/3) for selective indicator computation"),
):
    """Compute all Elder indicators and return aligned per-bar data.

    Uses singleflight pattern + cache to prevent duplicate computation
    from React Strict Mode double-mounts.
    """
    cache_key = f"{symbol}:{exchange}:{interval}:{days}:{screen}"

    # Fast path: return cached result
    if cache_key in _indicator_cache:
        ts, cached = _indicator_cache[cache_key]
        if (_time.time() - ts) < _INDICATOR_CACHE_TTL:
            logger.debug("Serving cached indicators for {}", cache_key)
            return cached

    # Singleflight: only one computation per cache key at a time
    if cache_key not in _indicator_locks:
        _indicator_locks[cache_key] = asyncio.Lock()

    async with _indicator_locks[cache_key]:
        # Re-check cache inside lock
        if cache_key in _indicator_cache:
            ts, cached = _indicator_cache[cache_key]
            if (_time.time() - ts) < _INDICATOR_CACHE_TTL:
                return cached

        # Fetch candle data (async — uses candle singleflight/cache)
        df = await _get_candle_df(symbol, exchange, interval, days)
        if df is None or df.empty:
            return {"data": [], "symbol": symbol, "error": "No candle data"}

        df = _ensure_columns(df)
        n = len(df)

        # Run CPU-bound indicator computation in thread pool (doesn't block event loop)
        result_data = await asyncio.to_thread(_compute_indicators_sync, df, symbol, interval, screen)

        response = {
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "count": n,
            "data": result_data,
        }

        # Cache the result
        _indicator_cache[cache_key] = (_time.time(), response)

        return response
