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

    def get_all_summaries(self) -> list[dict]:
        """Compact summaries for all active sessions (command center)."""
        return [s.get_summary() for s in self._sessions.values() if s.active]

    def get_contract_status(self) -> list[dict]:
        """Contract expiry status for all active sessions."""
        from datetime import datetime
        results = []
        for key, session in self._sessions.items():
            if not session.active:
                continue
            days = None
            if session.expiry_date:
                days = (session.expiry_date - datetime.now()).days

            threshold = 15 if session.exchange == "MCX" else 7
            status = "OK"
            if days is not None:
                if days <= 0:
                    status = "EXPIRED"
                elif days <= threshold:
                    status = "ROLLOVER_NEEDED"
                elif days <= threshold * 2:
                    status = "WARNING"

            results.append({
                "symbol": session.symbol,
                "exchange": session.exchange,
                "token": session.token,
                "contract": session.contract_symbol,
                "expiry_date": session.expiry_date.strftime("%Y-%m-%d") if session.expiry_date else None,
                "days_to_expiry": days,
                "status": status,
                "threshold": threshold,
            })
        return results

    async def check_and_rollover(self):
        """Check all sessions for expiry and auto-rollover if needed."""
        from datetime import datetime
        contracts = self.get_contract_status()
        for c in contracts:
            if c["status"] in ("ROLLOVER_NEEDED", "EXPIRED"):
                sym, exch = c["symbol"], c["exchange"]
                logger.warning("Contract rollover needed: {}:{} ({}d left, contract={})",
                              sym, exch, c["days_to_expiry"], c["contract"])
                try:
                    await self._do_rollover(sym, exch)
                except Exception as e:
                    logger.error("Rollover failed for {}:{}: {}", sym, exch, e)

    async def _do_rollover(self, symbol: str, exchange: str):
        """Execute rollover: close positions, stop old session, start new one."""
        key = f"{symbol}:{exchange}"
        old_session = self._sessions.get(key)
        if not old_session:
            return

        old_token = old_session.token
        old_contract = old_session.contract_symbol

        # 1. Close any open positions on old contract
        try:
            from app.database import async_session
            from app.pipeline import db_persistence as db
            async with async_session() as dbsession:
                positions = await db.load_open_positions_by_symbol(dbsession, symbol)
                for pos in positions:
                    ltp = None
                    screen2_tf = old_session.screen_timeframes.get("2", "1d")
                    df = old_session.candle_buffers.get(screen2_tf)
                    if df is not None and not df.empty:
                        ltp = float(df.iloc[-1].get("close", 0))
                    if ltp and ltp > 0:
                        await db.close_position(dbsession, pos.id, ltp)
                        logger.info("Rollover: closed {} {} @ {}", pos.direction, symbol, ltp)
        except Exception as e:
            logger.warning("Rollover position close failed: {}", e)

        # 2. Stop old session
        await self.stop_tracking(symbol, exchange)

        # 3. Resolve new token
        new_token = await self._resolve_token(symbol, exchange)
        if not new_token or new_token == old_token:
            logger.error("Rollover: no new contract found for {}:{}", symbol, exchange)
            return

        # 4. Start new session
        new_session = await self.start_tracking(symbol, exchange)

        # 5. Subscribe new token on feed
        try:
            from app.broker.websocket_feed import market_feed
            if market_feed.is_connected:
                market_feed.subscribe([new_token], exchange)
        except Exception:
            pass

        # 6. Save rollover history to DB
        try:
            from app.database import async_session
            from app.pipeline import db_persistence as db
            async with async_session() as dbsession:
                await db.save_rollover(
                    dbsession, symbol, exchange,
                    old_token, old_contract or "",
                    new_token, new_session.contract_symbol or "",
                    old_session.expiry_date.strftime("%Y-%m-%d") if old_session.expiry_date else "",
                    new_session.expiry_date.strftime("%Y-%m-%d") if new_session.expiry_date else "",
                )
        except Exception as e:
            logger.warning("Rollover history save failed: {}", e)

        # 7. Notify
        logger.info("ROLLOVER COMPLETE: {}:{} {} -> {} (new token={})",
                    symbol, exchange, old_contract, new_session.contract_symbol, new_token)
        try:
            from app.notifications.telegram import _send
            await _send(
                f"🔄 <b>CONTRACT ROLLOVER: {symbol}</b>\n\n"
                f"Old: {old_contract} (token {old_token})\n"
                f"New: {new_session.contract_symbol} (token {new_token})\n"
                f"Expiry: {new_session.expiry_date.strftime('%Y-%m-%d') if new_session.expiry_date else '?'}\n"
                f"Days left: {new_session.days_to_expiry}"
            )
        except Exception:
            pass

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
