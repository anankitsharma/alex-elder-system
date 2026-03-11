"""Historical candle data fetcher using Angel One SmartAPI."""

from datetime import datetime, timedelta

import pandas as pd
from loguru import logger

from app.broker.angel_client import angel

# Angel One interval mapping
INTERVAL_MAP = {
    "1m": "ONE_MINUTE",
    "5m": "FIVE_MINUTE",
    "15m": "FIFTEEN_MINUTE",
    "30m": "THIRTY_MINUTE",
    "1h": "ONE_HOUR",
    "1d": "ONE_DAY",
}


def fetch_historical_candles(
    symbol_token: str,
    exchange: str,
    interval: str = "1d",
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> pd.DataFrame:
    """Fetch historical OHLCV data from Angel One.

    Args:
        symbol_token: Angel One instrument token
        exchange: Exchange segment (NSE, NFO, BSE, MCX)
        interval: Candle interval (1m, 5m, 15m, 30m, 1h, 1d)
        from_date: Start date (default: 365 days ago for daily)
        to_date: End date (default: now)

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
    """
    if interval not in INTERVAL_MAP:
        raise ValueError(f"Invalid interval '{interval}'. Use: {list(INTERVAL_MAP.keys())}")

    angel_interval = INTERVAL_MAP[interval]

    if to_date is None:
        to_date = datetime.now()
    if from_date is None:
        if interval == "1d":
            from_date = to_date - timedelta(days=365)
        elif interval in ("1h", "30m"):
            from_date = to_date - timedelta(days=60)
        else:
            from_date = to_date - timedelta(days=30)

    params = {
        "exchange": exchange,
        "symboltoken": symbol_token,
        "interval": angel_interval,
        "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
        "todate": to_date.strftime("%Y-%m-%d %H:%M"),
    }

    logger.debug("Fetching candles: {} {} {} from {} to {}",
                 exchange, symbol_token, interval,
                 from_date.strftime("%Y-%m-%d"), to_date.strftime("%Y-%m-%d"))

    try:
        data = angel.historical.getCandleData(params)
    except Exception as e:
        logger.error("Historical data fetch failed: {}", e)
        return pd.DataFrame()

    if not data or not data.get("data"):
        logger.warning("No historical data returned for token {}", symbol_token)
        return pd.DataFrame()

    candles = data["data"]
    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Convert to float
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    df["volume"] = df["volume"].astype(int)

    logger.info("Fetched {} candles for token {} ({})", len(df), symbol_token, interval)
    return df


def fetch_daily_candles(symbol_token: str, exchange: str = "NSE", days: int = 365) -> pd.DataFrame:
    """Convenience: fetch daily candles for the past N days."""
    return fetch_historical_candles(
        symbol_token=symbol_token,
        exchange=exchange,
        interval="1d",
        from_date=datetime.now() - timedelta(days=days),
        to_date=datetime.now(),
    )


def fetch_weekly_candles(symbol_token: str, exchange: str = "NSE", days: int = 730) -> pd.DataFrame:
    """Fetch daily candles and resample to weekly OHLCV."""
    df = fetch_historical_candles(
        symbol_token=symbol_token,
        exchange=exchange,
        interval="1d",
        from_date=datetime.now() - timedelta(days=days),
        to_date=datetime.now(),
    )
    if df.empty:
        return df

    df = df.set_index("timestamp")
    weekly = df.resample("W").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()

    return weekly.reset_index()
