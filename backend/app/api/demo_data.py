"""Generate realistic demo OHLCV data when broker session is unavailable.

This ensures the dashboard always shows functional charts even without
a live Angel One connection. Data is synthetic but follows realistic
price patterns (random walk with drift, proper OHLC relationships).
"""

import math
import random
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from loguru import logger

# Realistic base prices for common Indian stocks
_BASE_PRICES: dict[str, float] = {
    "RELIANCE": 2950.0,
    "HDFCBANK": 1720.0,
    "INFY": 1850.0,
    "TCS": 4200.0,
    "SBIN": 820.0,
    "ITC": 475.0,
    "ICICIBANK": 1280.0,
    "HINDUNILVR": 2500.0,
    "BHARTIARTL": 1680.0,
    "KOTAKBANK": 1850.0,
    "LT": 3600.0,
    "AXISBANK": 1180.0,
    "BAJFINANCE": 7200.0,
    "MARUTI": 12500.0,
    "WIPRO": 480.0,
    "TITAN": 3350.0,
    "SUNPHARMA": 1750.0,
    "HCLTECH": 1820.0,
    "ULTRACEMCO": 11200.0,
    "ONGC": 275.0,
    "TATAMOTORS": 1050.0,
    "M&M": 2850.0,
    "NTPC": 400.0,
    "POWERGRID": 310.0,
    "JSWSTEEL": 980.0,
    "TATASTEEL": 155.0,
    "ADANIENT": 3100.0,
    "ADANIPORTS": 1400.0,
    "COALINDIA": 500.0,
    "BPCL": 310.0,
    "NIFTY": 22500.0,
    "BANKNIFTY": 48000.0,
    "SENSEX": 74000.0,
}

_DEFAULT_PRICE = 1500.0


def _generate_ohlcv(
    base_price: float,
    bars: int,
    interval_minutes: int,
    start_date: datetime,
    volatility: float = 0.015,
    drift: float = 0.0001,
) -> list[dict]:
    """Generate realistic OHLCV bars using geometric Brownian motion.

    Creates proper OHLC relationships: high >= max(open, close),
    low <= min(open, close), volume correlates with price movement.
    """
    candles = []
    price = base_price
    avg_volume = 500_000 if interval_minutes >= 1440 else 50_000

    # Scale volatility by timeframe
    vol = volatility * math.sqrt(interval_minutes / 1440)

    for i in range(bars):
        # Skip weekends for daily+ timeframes
        if interval_minutes >= 1440:
            ts = start_date + timedelta(days=i)
            while ts.weekday() >= 5:  # Saturday=5, Sunday=6
                ts += timedelta(days=1)
            start_date = ts - timedelta(days=i - 1) if i > 0 else start_date
        else:
            ts = start_date + timedelta(minutes=i * interval_minutes)
            # Skip non-market hours (9:15 AM - 3:30 PM IST)
            hour = ts.hour
            if hour < 9 or (hour == 9 and ts.minute < 15) or hour >= 16:
                continue

        # Price movement (geometric Brownian motion)
        ret = drift + vol * random.gauss(0, 1)
        # Add slight mean reversion
        ret -= 0.001 * (price / base_price - 1)
        price *= (1 + ret)

        open_price = price
        # Intrabar movement
        intra_vol = vol * 0.6
        close_price = open_price * (1 + intra_vol * random.gauss(0, 1))

        high = max(open_price, close_price) * (1 + abs(random.gauss(0, intra_vol * 0.3)))
        low = min(open_price, close_price) * (1 - abs(random.gauss(0, intra_vol * 0.3)))

        # Volume correlates with absolute price change
        change_pct = abs(close_price - open_price) / open_price
        volume = int(avg_volume * (1 + change_pct * 20) * (0.5 + random.random()))

        candles.append({
            "timestamp": ts,
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close_price, 2),
            "volume": volume,
        })

        price = close_price

    return candles


def get_demo_candles(
    symbol: str,
    exchange: str,
    interval: str,
    days: int,
) -> Optional[pd.DataFrame]:
    """Get demo candle data for a symbol. Returns DataFrame or None."""

    base_price = _BASE_PRICES.get(symbol.upper(), _DEFAULT_PRICE)
    # Add slight randomness to base price so it's not always the same
    base_price *= (0.95 + random.random() * 0.1)

    # Map interval to minutes
    interval_map = {
        "1m": 1, "3m": 3, "5m": 5, "10m": 10,
        "15m": 15, "30m": 30, "1h": 60, "1d": 1440,
    }
    interval_min = interval_map.get(interval, 1440)

    # Calculate number of bars
    if interval_min >= 1440:
        bars = days
    else:
        # Trading hours: ~375 minutes per day
        bars_per_day = 375 // interval_min
        bars = min(bars_per_day * days, 5000)

    start_date = datetime.now() - timedelta(days=days)
    candles = _generate_ohlcv(base_price, bars, interval_min, start_date)

    if not candles:
        return None

    return pd.DataFrame(candles)


def get_demo_weekly_candles(
    symbol: str,
    exchange: str,
    days: int,
) -> Optional[pd.DataFrame]:
    """Get demo weekly candle data (resampled from daily)."""
    daily = get_demo_candles(symbol, exchange, "1d", days)
    if daily is None or daily.empty:
        return None

    daily["timestamp"] = pd.to_datetime(daily["timestamp"])
    daily = daily.set_index("timestamp")

    weekly = daily.resample("W-FRI").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()

    weekly = weekly.reset_index()
    return weekly
