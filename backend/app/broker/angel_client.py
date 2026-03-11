"""Angel One SmartAPI client wrapper — handles auth, session, and token management."""

import pyotp
from loguru import logger
from SmartApi import SmartConnect

from app.config import settings


class AngelClient:
    """Wrapper around SmartAPI for trading operations."""

    def __init__(self):
        self._trading_client: SmartConnect | None = None
        self._hist_client: SmartConnect | None = None
        self._feed_client: SmartConnect | None = None
        self._feed_token: str | None = None
        self._auth_token: str | None = None
        self._refresh_token: str | None = None

    def _generate_totp(self) -> str:
        return pyotp.TOTP(settings.angel_totp_secret).now()

    def login_trading(self) -> dict:
        """Login with the trading API key. Used for order placement and account info."""
        self._trading_client = SmartConnect(api_key=settings.angel_api_key)
        totp = self._generate_totp()
        data = self._trading_client.generateSession(
            settings.angel_client_code,
            settings.angel_client_password,
            totp,
        )
        if data.get("status"):
            self._auth_token = data["data"]["jwtToken"]
            self._refresh_token = data["data"]["refreshToken"]
            self._feed_token = self._trading_client.getfeedToken()
            logger.info("Trading API login successful for {}", settings.angel_client_code)
        else:
            logger.error("Trading API login failed: {}", data.get("message", "Unknown error"))
        return data

    def login_historical(self) -> dict:
        """Login with the historical data API key."""
        self._hist_client = SmartConnect(api_key=settings.angel_hist_api_key)
        totp = self._generate_totp()
        data = self._hist_client.generateSession(
            settings.angel_client_code,
            settings.angel_client_password,
            totp,
        )
        if data.get("status"):
            logger.info("Historical API login successful")
        else:
            logger.error("Historical API login failed: {}", data.get("message", "Unknown error"))
        return data

    def login_feed(self) -> dict:
        """Login with the WebSocket feed API key."""
        self._feed_client = SmartConnect(api_key=settings.angel_feed_api_key)
        totp = self._generate_totp()
        data = self._feed_client.generateSession(
            settings.angel_client_code,
            settings.angel_client_password,
            totp,
        )
        if data.get("status"):
            self._feed_token = self._feed_client.getfeedToken()
            logger.info("Feed API login successful")
        else:
            logger.error("Feed API login failed: {}", data.get("message", "Unknown error"))
        return data

    def login_all(self) -> bool:
        """Login to all three API sessions. Returns True if all succeed."""
        results = []
        for name, login_fn in [
            ("trading", self.login_trading),
            ("historical", self.login_historical),
            ("feed", self.login_feed),
        ]:
            try:
                result = login_fn()
                results.append(result.get("status", False))
            except Exception as e:
                logger.error("{} login exception: {}", name, e)
                results.append(False)
        return all(results)

    @property
    def trading(self) -> SmartConnect:
        if not self._trading_client:
            raise RuntimeError("Trading client not logged in. Call login_trading() first.")
        return self._trading_client

    @property
    def historical(self) -> SmartConnect:
        if not self._hist_client:
            raise RuntimeError("Historical client not logged in. Call login_historical() first.")
        return self._hist_client

    @property
    def feed(self) -> SmartConnect:
        if not self._feed_client:
            raise RuntimeError("Feed client not logged in. Call login_feed() first.")
        return self._feed_client

    @property
    def feed_token(self) -> str:
        if not self._feed_token:
            raise RuntimeError("Feed token not available. Login first.")
        return self._feed_token

    @property
    def auth_token(self) -> str:
        if not self._auth_token:
            raise RuntimeError("Auth token not available. Login first.")
        return self._auth_token

    def get_profile(self) -> dict:
        return self.trading.getProfile(self._refresh_token)

    def get_rms(self) -> dict:
        """Get risk management system data (margins, funds)."""
        return self.trading.rmsLimit()

    def get_holdings(self) -> dict:
        return self.trading.holding()

    def get_positions(self) -> dict:
        return self.trading.position()

    def get_order_book(self) -> dict:
        return self.trading.orderBook()


# Singleton instance
angel = AngelClient()
