"""SmartWebSocketV2 live data streaming from Angel One."""

import asyncio
import json
import threading
import time
from typing import Callable

from loguru import logger
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

from app.broker.angel_client import angel
from app.broker.instruments import EXCHANGE_MAP
from app.config import settings

# Subscription modes
MODE_LTP = 1       # Last Traded Price only
MODE_QUOTE = 2     # OHLC + volume
MODE_SNAP = 3      # Full market depth

# Reconnection settings — infinite retry (never give up)
RECONNECT_BASE_DELAY = 2  # seconds
RECONNECT_MAX_DELAY = 300  # 5 min cap
STALE_DATA_TIMEOUT = 60  # seconds with no data → force reconnect


class MarketFeed:
    """Manages Angel One WebSocket connection for live market data."""

    def __init__(self):
        self._ws: SmartWebSocketV2 | None = None
        self._subscriptions: dict[str, list[str]] = {}  # exchange -> [tokens]
        self._callbacks: list[Callable] = []
        self._running = False
        self._should_reconnect = True
        self._reconnect_attempts = 0
        self._last_data_time: float = 0
        self._reconnect_thread: threading.Thread | None = None
        self._tick_count: int = 0

    def add_callback(self, callback: Callable):
        """Register a callback for incoming tick data."""
        self._callbacks.append(callback)

    def _on_data(self, ws, message):
        """Called when data is received from WebSocket."""
        self._last_data_time = time.time()
        self._reconnect_attempts = 0  # Reset on successful data

        # SmartWebSocketV2 sends data as dict with token, ltp, etc.
        # Log first few ticks for debugging
        if self._tick_count < 3:
            logger.info("Feed tick #{}: type={} keys={}", self._tick_count,
                        type(message).__name__,
                        list(message.keys())[:8] if isinstance(message, dict) else str(message)[:100])
        self._tick_count += 1

        for cb in self._callbacks:
            try:
                cb(message)
            except Exception as e:
                logger.error("Callback error: {}", e)

    def _on_open(self, ws):
        """Called when WebSocket connection opens."""
        logger.info("Market feed WebSocket connected")
        self._running = True
        self._reconnect_attempts = 0
        # Re-subscribe to all instruments
        if self._subscriptions:
            self._subscribe_all()

    def _on_error(self, ws, error):
        logger.error("Market feed WebSocket error: {}", error)

    def _on_close(self, ws):
        logger.warning("Market feed WebSocket closed")
        self._running = False
        # Auto-reconnect with exponential backoff + jitter (infinite retry)
        if self._should_reconnect:
            import random
            delay = min(
                RECONNECT_BASE_DELAY * (2 ** min(self._reconnect_attempts, 8)),
                RECONNECT_MAX_DELAY,
            )
            # Add jitter: ±25% to prevent reconnect storms
            delay *= (0.75 + random.random() * 0.5)
            self._reconnect_attempts += 1
            logger.info(
                "Reconnecting market feed in {:.1f}s (attempt {})",
                delay, self._reconnect_attempts,
            )
            self._reconnect_thread = threading.Thread(
                target=self._delayed_reconnect, args=(delay,), daemon=True
            )
            self._reconnect_thread.start()

    def _delayed_reconnect(self, delay: float):
        """Reconnect after a delay (runs in background thread).

        Outside market hours (weekends, holidays, off-hours), waits longer
        to avoid wasting resources and broker API rate limits.
        """
        time.sleep(delay)

        # Check if any market is open — if not, sleep until next likely open
        try:
            from app.pipeline.holidays import is_trading_day
            from datetime import date as _date
            if not is_trading_day(_date.today()):
                logger.info("Non-trading day — delaying feed reconnect by 60min")
                time.sleep(3600)  # 1 hour
                return  # Will retry on next _on_close cycle
        except Exception:
            pass  # If check fails, proceed with reconnect
        if self._should_reconnect and not self._running:
            try:
                self.connect()
            except Exception as e:
                logger.error("Reconnect failed: {}", e)

    def _subscribe_all(self):
        """Subscribe to all registered instruments."""
        if not self._ws:
            return
        for exchange, tokens in self._subscriptions.items():
            if not tokens:
                continue
            exchange_code = EXCHANGE_MAP.get(exchange, 1)
            token_list = [{"exchangeType": exchange_code, "tokens": tokens}]
            self._ws.subscribe("abc123", MODE_QUOTE, token_list)
            logger.info("Subscribed to {} tokens on {}", len(tokens), exchange)

    def subscribe(self, tokens: list[str], exchange: str = "NSE"):
        """Add tokens to subscription list."""
        if exchange not in self._subscriptions:
            self._subscriptions[exchange] = []
        new_tokens = [t for t in tokens if t not in self._subscriptions[exchange]]
        self._subscriptions[exchange].extend(new_tokens)

        # If already connected, subscribe immediately
        if self._running and self._ws and new_tokens:
            exchange_code = EXCHANGE_MAP.get(exchange, 1)
            token_list = [{"exchangeType": exchange_code, "tokens": new_tokens}]
            self._ws.subscribe("abc123", MODE_QUOTE, token_list)
            logger.info("Live-subscribed to {} new tokens on {}", len(new_tokens), exchange)

    def unsubscribe(self, tokens: list[str], exchange: str = "NSE"):
        """Remove tokens from subscription list."""
        if exchange in self._subscriptions:
            self._subscriptions[exchange] = [
                t for t in self._subscriptions[exchange] if t not in tokens
            ]
        if self._running and self._ws:
            exchange_code = EXCHANGE_MAP.get(exchange, 1)
            token_list = [{"exchangeType": exchange_code, "tokens": tokens}]
            self._ws.unsubscribe("abc123", MODE_QUOTE, token_list)

    def connect(self):
        """Initialize and connect the WebSocket.

        On reconnect, refreshes auth/feed tokens from broker session
        to handle session expiry.
        """
        try:
            # Refresh tokens if this is a reconnect attempt
            if self._reconnect_attempts > 0:
                try:
                    angel.refresh_session()
                    logger.info("Refreshed broker session tokens for feed reconnect")
                except Exception as e:
                    logger.warning("Token refresh failed (using existing): {}", e)

            self._ws = SmartWebSocketV2(
                auth_token=angel.auth_token,
                api_key=settings.angel_feed_api_key,
                client_code=settings.angel_client_code,
                feed_token=angel.feed_token,
            )

            self._ws.on_data = self._on_data
            self._ws.on_open = self._on_open
            self._ws.on_error = self._on_error
            self._ws.on_close = self._on_close

            logger.info("Starting market feed WebSocket...")
            self._ws.connect()
        except Exception as e:
            logger.error("Failed to connect market feed: {}", e)
            raise

    def disconnect(self):
        """Disconnect the WebSocket (stops reconnection)."""
        self._should_reconnect = False
        if self._ws:
            try:
                self._ws.close_connection()
            except Exception:
                pass
            self._running = False
            logger.info("Market feed disconnected")

    @property
    def is_connected(self) -> bool:
        return self._running

    @property
    def last_data_age(self) -> float:
        """Seconds since last data received. -1 if never received."""
        if self._last_data_time == 0:
            return -1
        return time.time() - self._last_data_time

    def check_stale_and_reconnect(self):
        """Force reconnect if no data received for STALE_DATA_TIMEOUT seconds.

        Call this periodically from the heartbeat loop. Only triggers during
        market hours when we expect data flow.
        """
        if not self._running or not self._should_reconnect:
            return
        age = self.last_data_age
        if age > STALE_DATA_TIMEOUT and age != -1:
            logger.warning(
                "Market feed stale ({:.0f}s no data) — forcing reconnect",
                age,
            )
            self._running = False
            try:
                if self._ws:
                    self._ws.close_connection()
            except Exception:
                pass
            # Trigger reconnect
            self._on_close(self._ws)


# Singleton
market_feed = MarketFeed()
