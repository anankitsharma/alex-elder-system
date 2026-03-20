"""CandleBuilder — converts ticks into OHLCV candles.

One instance per AssetSession. Aggregates incoming ticks into bars of
the configured timeframe, emitting completed bars when a new period starts.
"""

from datetime import datetime, timedelta, time as dt_time
from typing import Callable, Optional

import pytz
from loguru import logger

from app.pipeline.market_hours import get_session, MarketSession, IST

# Timeframe → minutes (intraday only)
TIMEFRAME_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
}


def _floor_timestamp(dt: datetime, minutes: int) -> datetime:
    """Floor a timestamp to the nearest bar boundary."""
    # Ensure we're working in IST
    if dt.tzinfo is None:
        dt = IST.localize(dt)
    else:
        dt = dt.astimezone(IST)

    # Floor to interval
    minute = (dt.minute // minutes) * minutes
    return dt.replace(minute=minute, second=0, microsecond=0)


class CandleBuilder:
    """Aggregates ticks into OHLCV bars for a single timeframe."""

    def __init__(
        self,
        timeframe: str,
        on_bar_close: Optional[Callable] = None,
        exchange: str = "NSE",
        symbol: str = "",
    ):
        """
        Args:
            timeframe: Bar size (1m, 5m, 15m, 30m, 1h, 1d)
            on_bar_close: Callback(timeframe, bar_dict) when a bar completes
            exchange: Exchange code (NSE, NFO, MCX, etc.) for market hours
            symbol: Trading symbol (needed for MCX agri/non-agri classification)
        """
        self.timeframe = timeframe
        self.on_bar_close = on_bar_close
        self.exchange = exchange
        self.symbol = symbol
        self._market_session: MarketSession = get_session(exchange, symbol)

        self._current_bar: Optional[dict] = None
        self._current_period: Optional[datetime] = None
        self._prev_cum_volume: int = 0

        if timeframe in TIMEFRAME_MINUTES:
            self._interval_minutes = TIMEFRAME_MINUTES[timeframe]
        elif timeframe == "1d":
            self._interval_minutes = 0  # Special: daily
        else:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

    def on_tick(self, tick: dict) -> Optional[dict]:
        """Process an incoming tick.

        Args:
            tick: dict with at minimum 'ltp' (last traded price).
                  Optional: 'timestamp', 'volume_trade_today' (cumulative volume).

        Returns:
            Completed bar dict if a bar closed, else None.
        """
        raw_ltp = float(tick.get("last_traded_price", 0) or tick.get("ltp", 0))
        if raw_ltp <= 0:
            return None
        # SmartWebSocketV2 sends prices in paise (divide by 100 for rupees)
        ltp = raw_ltp / 100 if raw_ltp > 100000 else raw_ltp

        # Parse timestamp
        raw_ts = tick.get("timestamp") or tick.get("exchange_timestamp")
        if raw_ts:
            if isinstance(raw_ts, str):
                try:
                    now = datetime.fromisoformat(raw_ts)
                except ValueError:
                    now = datetime.now(IST)
            elif isinstance(raw_ts, (int, float)):
                # SmartWebSocketV2 may send epoch in seconds or milliseconds
                ts_val = raw_ts / 1000 if raw_ts > 1e12 else raw_ts
                try:
                    now = datetime.fromtimestamp(ts_val, tz=IST)
                except (OSError, ValueError):
                    now = datetime.now(IST)
            else:
                now = datetime.now(IST)
        else:
            now = datetime.now(IST)

        if now.tzinfo is None:
            now = IST.localize(now)

        # Skip ticks outside market hours for intraday
        if self._interval_minutes > 0 and not self._market_session.is_open(now):
            return None

        # Calculate volume delta from cumulative
        cum_vol = int(tick.get("volume_trade_today", 0) or tick.get("volume_traded_today", 0))
        if cum_vol > 0 and self._prev_cum_volume > 0:
            vol_delta = max(cum_vol - self._prev_cum_volume, 0)
        elif cum_vol > 0:
            vol_delta = 0  # First tick — can't compute delta
        else:
            vol_delta = int(tick.get("last_traded_quantity", 0) or tick.get("volume", 0))
        self._prev_cum_volume = cum_vol

        # Determine bar period
        if self._interval_minutes > 0:
            bar_period = _floor_timestamp(now, self._interval_minutes)
        else:
            # Daily: period is the date at market close
            ist_now = now.astimezone(IST)
            close = self._market_session.close_time
            bar_period = ist_now.replace(
                hour=close.hour, minute=close.minute, second=0, microsecond=0
            )

        completed_bar = None

        # Check if we've moved to a new bar period
        if self._current_period is not None and bar_period > self._current_period:
            # Complete the current bar
            completed_bar = self._current_bar.copy()
            if self.on_bar_close:
                self.on_bar_close(self.timeframe, completed_bar)
            self._current_bar = None
            self._current_period = None

        # Start new bar or update existing
        if self._current_bar is None:
            self._current_bar = {
                "timestamp": bar_period.isoformat(),
                "open": ltp,
                "high": ltp,
                "low": ltp,
                "close": ltp,
                "volume": vol_delta,
            }
            self._current_period = bar_period
        else:
            self._current_bar["high"] = max(self._current_bar["high"], ltp)
            self._current_bar["low"] = min(self._current_bar["low"], ltp)
            self._current_bar["close"] = ltp
            self._current_bar["volume"] += vol_delta

        return completed_bar

    @property
    def running_bar(self) -> Optional[dict]:
        """Get the current in-progress bar (for display)."""
        return self._current_bar.copy() if self._current_bar else None

    def reset(self):
        """Reset builder state."""
        self._current_bar = None
        self._current_period = None
        self._prev_cum_volume = 0
