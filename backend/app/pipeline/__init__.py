"""Pipeline package — end-to-end trading pipeline manager.

Usage:
    from app.pipeline import pipeline_manager
    await pipeline_manager.start_tracking("RELIANCE", "NSE")
"""

from typing import Optional

from loguru import logger

from app.pipeline.asset_session import AssetSession


class PipelineManager:
    """Singleton managing AssetSession instances for tracked symbols."""

    def __init__(self):
        self._sessions: dict[str, AssetSession] = {}  # "RELIANCE:NSE" -> AssetSession
        self._token_map: dict[str, str] = {}  # token -> "RELIANCE:NSE"
        self._broadcast_fn: Optional[callable] = None

    def set_broadcast(self, fn):
        """Set the broadcast function for pipeline events."""
        self._broadcast_fn = fn

    async def start_tracking(self, symbol: str, exchange: str = "NSE") -> AssetSession:
        """Start tracking a symbol through the pipeline."""
        key = f"{symbol}:{exchange}"

        if key in self._sessions:
            session = self._sessions[key]
            if session.active:
                logger.info("Already tracking {}", key)
                return session
            # Restart inactive session
            del self._sessions[key]

        # Resolve token
        token = await self._resolve_token(symbol, exchange)
        if not token:
            raise ValueError(f"Could not resolve token for {symbol} on {exchange}")

        session = AssetSession(symbol, exchange, token)
        session._broadcast = self._broadcast_fn

        self._sessions[key] = session
        self._token_map[token] = key

        await session.start()
        logger.info("Pipeline tracking started: {}", key)
        return session

    async def stop_tracking(self, symbol: str, exchange: str = "NSE"):
        """Stop tracking a symbol."""
        key = f"{symbol}:{exchange}"
        session = self._sessions.get(key)
        if session:
            # Remove token mapping
            for token, k in list(self._token_map.items()):
                if k == key:
                    del self._token_map[token]
            session.stop()
            del self._sessions[key]
            logger.info("Pipeline tracking stopped: {}", key)

    def on_tick(self, tick_data):
        """Route incoming tick to the correct AssetSession by token."""
        if not self._sessions:
            return

        if isinstance(tick_data, dict):
            token = str(tick_data.get("token", ""))
        else:
            return

        key = self._token_map.get(token)
        if key and key in self._sessions:
            self._sessions[key].on_tick(tick_data)

    async def get_status(self) -> dict:
        """Get status of all active sessions."""
        return {
            "active_sessions": len(self._sessions),
            "sessions": {
                key: session.get_status()
                for key, session in self._sessions.items()
            },
        }

    def get_session(self, symbol: str, exchange: str = "NSE") -> Optional[AssetSession]:
        """Get an active session."""
        return self._sessions.get(f"{symbol}:{exchange}")

    async def get_backfill(self, symbol: str, exchange: str, since: str) -> dict:
        """Get candles since a timestamp for all active timeframes.

        Returns: { "1d": [candle_dicts], "1h": [...], ... }
        """
        key = f"{symbol}:{exchange}"
        session = self._sessions.get(key)
        if not session or not session.instrument_id:
            return {}

        from datetime import datetime
        from app.database import async_session as get_session
        from app.pipeline import db_persistence as db

        since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        result: dict[str, list[dict]] = {}

        async with get_session() as dbsession:
            for screen, tf in session.screen_timeframes.items():
                candles = await db.load_candles_since(
                    dbsession, session.instrument_id, tf, since_dt
                )
                if candles:
                    result[tf] = candles

        return result

    async def shutdown(self):
        """Shut down all sessions."""
        for key in list(self._sessions.keys()):
            self._sessions[key].stop()
        self._sessions.clear()
        self._token_map.clear()
        logger.info("PipelineManager shut down")

    async def _resolve_token(self, symbol: str, exchange: str) -> Optional[str]:
        """Resolve symbol to Angel One token."""
        try:
            from app.broker.instruments import download_scrip_master, lookup_token
            scrip_df = await download_scrip_master()
            token = lookup_token(scrip_df, symbol, exchange)
            if token:
                return token
        except Exception as e:
            logger.warning("Token resolution failed: {}", e)

        # Fallback: use symbol as token for demo mode
        logger.info("Using fallback token for {} (demo mode)", symbol)
        return symbol


# Singleton
pipeline_manager = PipelineManager()
