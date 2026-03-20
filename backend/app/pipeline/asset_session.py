"""AssetSession — core orchestrator for a single tracked symbol.

Ties together: CandleBuilder → IndicatorEngine → TripleScreen → Risk → Execute.
One instance per symbol being tracked by the pipeline.
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from loguru import logger

from app.config import settings
from app.database import async_session
from app.pipeline.candle_builder import CandleBuilder
from app.pipeline.indicator_engine import IndicatorEngine
from app.pipeline.utils import last_non_null, slope_of_last, trend_of_last
from app.pipeline import db_persistence as db


class AssetSession:
    """Manages the full pipeline for a single asset."""

    def __init__(self, symbol: str, exchange: str, token: str):
        self.symbol = symbol
        self.exchange = exchange
        self.token = token
        self.instrument_id: Optional[int] = None
        self.active = False

        # Candle buffers per timeframe: "1d" -> DataFrame
        self.candle_buffers: dict[str, pd.DataFrame] = {}

        # CandleBuilder per intraday timeframe
        self.candle_builders: dict[str, CandleBuilder] = {}

        # Latest indicator results per timeframe
        self.indicators: dict[str, dict] = {}

        # Latest Triple Screen analysis
        self.latest_analysis: Optional[dict] = None

        # Track last processed signal to avoid duplicates
        self._last_signal_key: Optional[str] = None

        # Alignment tracking for progressive alerts
        self._prev_alignment_level: int = 0
        self.alignment: dict = {
            "screen1": False, "screen2": False, "screen3": False,
            "level": 0, "direction": None, "description": "No setup",
        }

        # Indicator engines per timeframe
        self._engines: dict[str, IndicatorEngine] = {}

        # Screen timeframes (default EQUITY)
        self.screen_timeframes = {"1": "1w", "2": "1d", "3": "1h"}

        # Broadcast callback (set by PipelineManager)
        self._broadcast: Optional[callable] = None

    async def start(self):
        """Initialize session: resolve instrument, load history, compute indicators."""
        logger.info("Starting AssetSession for {}:{}", self.symbol, self.exchange)

        # Resolve instrument in DB
        async with async_session() as session:
            inst = await db.get_or_create_instrument(
                session, self.symbol, self.exchange, self.token
            )
            self.instrument_id = inst.id

        # Determine screen timeframes based on asset class
        await self._resolve_timeframes()

        # Load historical data for all screen timeframes
        await self._load_historical()

        # Create candle builders for intraday timeframes
        for screen, tf in self.screen_timeframes.items():
            if tf not in ("1w",):  # Weekly is resampled from daily
                self.candle_builders[tf] = CandleBuilder(
                    tf, on_bar_close=self._on_bar_close_sync
                )
                self._engines[tf] = IndicatorEngine(self.symbol, tf)

        # Also ensure daily engine exists (for weekly resampling)
        if "1d" not in self._engines:
            self._engines["1d"] = IndicatorEngine(self.symbol, "1d")
        if "1w" not in self._engines:
            self._engines["1w"] = IndicatorEngine(self.symbol, "1w")

        # Compute initial indicators for all timeframes
        for tf, df in self.candle_buffers.items():
            if not df.empty:
                screen_num = self._tf_to_screen(tf)
                engine = self._engines.get(tf)
                if engine:
                    self.indicators[tf] = engine.compute_for_screen(df, screen_num)

        # Run initial analysis
        await self._evaluate_signals()

        self.active = True
        logger.info(
            "AssetSession ready: {}:{} | screens: {} | candles: {}",
            self.symbol, self.exchange, self.screen_timeframes,
            {tf: len(df) for tf, df in self.candle_buffers.items()},
        )

        await self._broadcast_event("pipeline_status", self.get_status())

    async def _resolve_timeframes(self):
        """Get screen timeframes from timeframe_config."""
        try:
            from app.indicators.timeframe_config import (
                get_asset_class, get_timeframe_for_screen,
            )
            asset_class = get_asset_class(self.symbol, self.exchange)
            self.screen_timeframes = {
                "1": get_timeframe_for_screen(self.symbol, 1, self.exchange),
                "2": get_timeframe_for_screen(self.symbol, 2, self.exchange),
                "3": get_timeframe_for_screen(self.symbol, 3, self.exchange),
            }
            logger.info("Asset class: {} | Timeframes: {}", asset_class, self.screen_timeframes)
        except Exception as e:
            logger.warning("Timeframe resolution failed, using defaults: {}", e)

    async def _load_historical(self):
        """Load historical candles from broker (or demo fallback)."""
        loaded_daily = False

        for screen, tf in self.screen_timeframes.items():
            if tf == "1w":
                # Weekly is resampled from daily — load daily first if needed
                if not loaded_daily:
                    await self._load_timeframe("1d", days=730)
                    loaded_daily = True
                # Resample daily → weekly
                daily_df = self.candle_buffers.get("1d", pd.DataFrame())
                if not daily_df.empty:
                    self.candle_buffers["1w"] = self._resample_weekly(daily_df)
                continue

            days = {"1d": 365, "1h": 90, "15m": 30, "5m": 14, "1m": 7}.get(tf, 365)

            # Avoid double-loading daily
            if tf == "1d" and loaded_daily:
                continue

            await self._load_timeframe(tf, days)
            if tf == "1d":
                loaded_daily = True

    async def _load_timeframe(self, timeframe: str, days: int):
        """Load historical data for a single timeframe."""
        df = pd.DataFrame()

        # Try broker first
        try:
            from app.broker.historical import fetch_historical_candles
            df = fetch_historical_candles(
                self.token, self.exchange, timeframe,
                from_date=datetime.now() - timedelta(days=days),
            )
        except Exception as e:
            logger.warning("Broker fetch failed for {} {}: {}", self.symbol, timeframe, e)

        # Fallback to demo
        if df is None or df.empty:
            try:
                from app.api.demo_data import get_demo_candles
                df = get_demo_candles(self.symbol, self.exchange, timeframe, days)
                logger.info("Using demo data for {} {}", self.symbol, timeframe)
            except Exception as e:
                logger.warning("Demo fallback failed: {}", e)
                df = pd.DataFrame()

        if df is not None and not df.empty:
            self.candle_buffers[timeframe] = df
            # Persist to DB
            try:
                async with async_session() as session:
                    candle_dicts = df.to_dict("records")
                    await db.save_candles(session, self.instrument_id, timeframe, candle_dicts)
            except Exception as e:
                logger.warning("DB candle save failed: {}", e)

    def _resample_weekly(self, daily_df: pd.DataFrame) -> pd.DataFrame:
        """Resample daily candles to weekly."""
        df = daily_df.copy()
        ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
        if ts_col not in df.columns:
            return pd.DataFrame()

        df = df.set_index(ts_col)
        weekly = df.resample("W").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()
        return weekly.reset_index().rename(columns={"index": "timestamp"})

    def on_tick(self, tick: dict):
        """Process incoming tick — route to all candle builders.

        Called from the async tick poller (not from the feed thread directly),
        so we can safely schedule async tasks.
        """
        if not self.active:
            return

        for tf, builder in self.candle_builders.items():
            completed = builder.on_tick(tick)
            if completed:
                self._schedule_async(self._on_new_candle(tf, completed))

        # Broadcast running bar for display
        self._broadcast_running_bar()

    def _schedule_async(self, coro):
        """Schedule an async coroutine — queues it for the tick poller if from feed thread."""
        from app.ws.market_stream import _main_loop
        if _main_loop and not _main_loop.is_closed():
            try:
                # Try direct if we're on the event loop thread
                asyncio.ensure_future(coro)
            except RuntimeError:
                # From feed thread — can't schedule directly on Windows
                # The tick poller handles this via _broadcast_running_bar_sync
                pass

    def _on_bar_close_sync(self, timeframe: str, bar: dict):
        """Sync callback from CandleBuilder — just for logging."""
        logger.debug("Bar closed: {} {} O={} H={} L={} C={} V={}",
                     self.symbol, timeframe,
                     bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"])

    async def _on_new_candle(self, timeframe: str, candle: dict):
        """Handle a newly completed candle bar."""
        # Append to buffer
        new_row = pd.DataFrame([candle])
        if "timestamp" not in new_row.columns and "datetime" not in new_row.columns:
            ts_val = candle.get("timestamp", datetime.now().isoformat())
            new_row["timestamp"] = [ts_val]

        if timeframe in self.candle_buffers and not self.candle_buffers[timeframe].empty:
            self.candle_buffers[timeframe] = pd.concat(
                [self.candle_buffers[timeframe], new_row], ignore_index=True
            )
        else:
            self.candle_buffers[timeframe] = new_row

        # Persist to DB
        try:
            async with async_session() as session:
                await db.save_candles(session, self.instrument_id, timeframe, [candle])
        except Exception as e:
            logger.warning("DB candle save failed: {}", e)

        # If daily candle closed, resample weekly
        if timeframe == "1d" and "1w" in [self.screen_timeframes.get(s) for s in ("1", "2", "3")]:
            daily_df = self.candle_buffers.get("1d", pd.DataFrame())
            if not daily_df.empty:
                self.candle_buffers["1w"] = self._resample_weekly(daily_df)
                # Recompute weekly indicators
                engine = self._engines.get("1w")
                if engine and not self.candle_buffers["1w"].empty:
                    self.indicators["1w"] = engine.compute_for_screen(
                        self.candle_buffers["1w"], screen=1
                    )

        # Compute indicators for affected screens
        screen_num = self._tf_to_screen(timeframe)
        engine = self._engines.get(timeframe)
        if engine:
            df = self.candle_buffers.get(timeframe, pd.DataFrame())
            if not df.empty:
                self.indicators[timeframe] = engine.compute_for_screen(df, screen_num)

        # Broadcast candle + indicators
        await self._broadcast_event("candle", {
            "symbol": self.symbol,
            "timeframe": timeframe,
            "candle": candle,
        })
        await self._broadcast_event("indicators", {
            "symbol": self.symbol,
            "timeframe": timeframe,
            "data": self.indicators.get(timeframe, {}),
        })

        # Update trailing stops on candle close (Elder's SafeZone method)
        await self._update_trailing_stops()

        # Evaluate signals
        await self._evaluate_signals()

    async def _check_stop_losses(self, current_price: float):
        """Check if any open position's stop has been breached. Close if so."""
        if current_price <= 0:
            return
        try:
            async with async_session() as session:
                positions = await db.load_open_positions_by_symbol(session, self.symbol)
                for pos in positions:
                    if not pos.stop_price or pos.stop_price <= 0:
                        continue
                    breached = False
                    if pos.direction == "LONG" and current_price <= pos.stop_price:
                        breached = True
                    elif pos.direction == "SHORT" and current_price >= pos.stop_price:
                        breached = True

                    if breached:
                        trade = await db.close_position(session, pos.id, current_price)
                        if trade:
                            pnl = (current_price - pos.entry_price) * pos.quantity if pos.direction == "LONG" \
                                else (pos.entry_price - current_price) * pos.quantity
                            logger.info(
                                "STOP HIT: {} {} closed @ {:.2f} (stop={:.2f}) P&L={:.2f}",
                                pos.direction, self.symbol, current_price, pos.stop_price, pnl,
                            )
                            await self._broadcast_event("position_closed", {
                                "symbol": self.symbol,
                                "direction": pos.direction,
                                "entry_price": pos.entry_price,
                                "exit_price": current_price,
                                "stop_price": pos.stop_price,
                                "quantity": pos.quantity,
                                "pnl": round(pnl, 2),
                                "reason": "STOP_LOSS",
                            })
                            # Telegram alert
                            try:
                                from app.notifications.telegram import _send
                                emoji = "🛑" if pnl < 0 else "✅"
                                await _send(
                                    f"{emoji} <b>STOP HIT: {self.symbol}</b>\n\n"
                                    f"Direction: {pos.direction}\n"
                                    f"Entry: ₹{pos.entry_price:,.2f} → Exit: ₹{current_price:,.2f}\n"
                                    f"Stop: ₹{pos.stop_price:,.2f}\n"
                                    f"P&L: <b>₹{pnl:,.2f}</b>\n"
                                    f"Qty: {pos.quantity}"
                                )
                            except Exception:
                                pass
        except Exception as e:
            logger.debug("Stop check failed for {}: {}", self.symbol, e)

    async def _update_trailing_stops(self):
        """Update open position stops using SafeZone (Elder's trailing stop method).

        Rules:
        - LONG: stop = max(current_stop, new_safezone_long) — only tightens up
        - SHORT: stop = min(current_stop, new_safezone_short) — only tightens down
        - Never widens the stop
        """
        try:
            screen2_tf = self.screen_timeframes.get("2", "1d")
            ind = self.indicators.get(screen2_tf, {})
            safezone_long = last_non_null(ind.get("safezone_long", []))
            safezone_short = last_non_null(ind.get("safezone_short", []))

            if not safezone_long and not safezone_short:
                return

            # Current price
            ltp = None
            df = self.candle_buffers.get(screen2_tf, pd.DataFrame())
            if not df.empty:
                ltp = float(df.iloc[-1].get("close", 0))

            if not ltp:
                return

            async with async_session() as session:
                positions = await db.load_open_positions_by_symbol(session, self.symbol)
                for pos in positions:
                    new_stop = None
                    if pos.direction == "LONG" and safezone_long:
                        new_stop = safezone_long
                    elif pos.direction == "SHORT" and safezone_short:
                        new_stop = safezone_short

                    if new_stop:
                        old_stop = pos.stop_price or 0
                        await db.update_position_stop(session, pos.id, new_stop, ltp)
                        # Check if stop actually tightened
                        if (pos.direction == "LONG" and new_stop > old_stop) or \
                           (pos.direction == "SHORT" and new_stop < old_stop):
                            logger.info(
                                "Trailing stop updated: {} {} {:.2f} → {:.2f}",
                                pos.direction, self.symbol, old_stop, new_stop,
                            )
                            await self._broadcast_event("trailing_stop_updated", {
                                "symbol": self.symbol,
                                "direction": pos.direction,
                                "old_stop": round(old_stop, 2),
                                "new_stop": round(new_stop, 2),
                                "ltp": round(ltp, 2),
                            })
        except Exception as e:
            logger.debug("Trailing stop update failed for {}: {}", self.symbol, e)

    async def _evaluate_signals(self):
        """Run Triple Screen analysis on latest indicator data."""
        try:
            from app.strategy.triple_screen import TripleScreenAnalysis

            ts = TripleScreenAnalysis()

            # Build screen data from indicators
            screen1_tf = self.screen_timeframes.get("1", "1w")
            screen2_tf = self.screen_timeframes.get("2", "1d")
            screen3_tf = self.screen_timeframes.get("3", "1h")

            ind1 = self.indicators.get(screen1_tf, {})
            ind2 = self.indicators.get(screen2_tf, {})

            if not ind1 or not ind2:
                return

            # Screen 1: Trend
            screen1 = {
                "macd_histogram_slope": slope_of_last(ind1.get("macd_histogram", [])),
                "impulse_signal": last_non_null(ind1.get("impulse_signal", []), "neutral"),
                "ema_trend": trend_of_last(ind1.get("ema13", [])),
            }

            # Screen 2: Oscillator
            screen2 = {
                "force_index_2": last_non_null(ind2.get("force_index_2", [])),
                "elder_ray_bear": last_non_null(ind2.get("elder_ray_bear", [])),
                "elder_ray_bull": last_non_null(ind2.get("elder_ray_bull", [])),
                "elder_ray_bear_trend": trend_of_last(ind2.get("elder_ray_bear", [])),
                "elder_ray_bull_trend": trend_of_last(ind2.get("elder_ray_bull", [])),
                "impulse_signal": last_non_null(ind2.get("impulse_signal", []), "neutral"),
            }

            # Value zone position
            vz_fast = last_non_null(ind2.get("value_zone_fast", []))
            vz_slow = last_non_null(ind2.get("value_zone_slow", []))
            candles_2 = self.candle_buffers.get(screen2_tf, pd.DataFrame())
            if not candles_2.empty and vz_fast and vz_slow:
                last_close = float(candles_2.iloc[-1].get("close", 0))
                lo, hi = min(vz_fast, vz_slow), max(vz_fast, vz_slow)
                if lo <= last_close <= hi:
                    screen2["value_zone_position"] = 0
                elif last_close > hi:
                    screen2["value_zone_position"] = 1
                else:
                    screen2["value_zone_position"] = -1
            else:
                screen2["value_zone_position"] = None

            # Screen 3: Entry precision
            screen3 = None
            if not candles_2.empty and len(candles_2) >= 2:
                prev = candles_2.iloc[-2]
                screen3 = {
                    "last_high": float(prev.get("high", 0)),
                    "last_low": float(prev.get("low", 0)),
                    "safezone_long": last_non_null(ind2.get("safezone_long", [])),
                    "safezone_short": last_non_null(ind2.get("safezone_short", [])),
                }

            analysis = ts.analyze(screen1, screen2, screen3)
            self.latest_analysis = analysis

            # ── Compute screen alignment ──
            s1_data = analysis.get("screen1", {})
            s2_data = analysis.get("screen2", {})
            rec = analysis.get("recommendation", {})
            tide = s1_data.get("tide")
            wave = s2_data.get("signal")
            action = rec.get("action", "WAIT")
            confidence = rec.get("confidence", 0)
            grade = analysis.get("grade", "D")

            # Screen 1 aligned = tide is clear (not neutral)
            s1_aligned = tide in ("BULLISH", "BEARISH")
            # Screen 2 aligned = wave signal matches tide direction
            s2_aligned = (
                (tide == "BULLISH" and wave == "BUY") or
                (tide == "BEARISH" and wave == "SELL")
            )
            # Screen 3 aligned = actionable signal with entry/stop
            s3_aligned = action != "WAIT" and confidence >= settings.min_signal_score

            level = int(s1_aligned) + int(s2_aligned) + int(s3_aligned)
            direction = "LONG" if tide == "BULLISH" else "SHORT" if tide == "BEARISH" else None

            descs = {
                0: "No setup",
                1: f"Tide {tide}" if s1_aligned else "No setup",
                2: f"Tide + Wave aligned ({direction})",
                3: f"FULL ALIGNMENT — {direction} ({grade})",
            }

            self.alignment = {
                "screen1": s1_aligned,
                "screen2": s2_aligned,
                "screen3": s3_aligned,
                "level": level,
                "direction": direction,
                "description": descs.get(level, "No setup"),
                "tide": tide,
                "wave": wave,
                "action": action,
                "grade": grade,
                "confidence": confidence,
            }

            # ── Progressive alignment alerts ──
            prev_level = self._prev_alignment_level
            if level > prev_level:
                try:
                    from app.notifications.telegram import _send
                    if level == 1 and prev_level == 0:
                        await _send(
                            f"📊 <b>{self.symbol}</b> — Screen 1 aligned\n"
                            f"Tide: <b>{tide}</b> | Direction: {direction}\n"
                            f"Watching for Screen 2 confirmation..."
                        )
                    elif level == 2:
                        emoji = "🟢" if direction == "LONG" else "🔴"
                        await _send(
                            f"{emoji} <b>{self.symbol}</b> — Tide + Wave ALIGNED\n"
                            f"Direction: <b>{direction}</b>\n"
                            f"Tide: {tide} | Wave: {wave}\n"
                            f"⏳ Waiting for entry trigger (Screen 3)..."
                        )
                    elif level == 3:
                        emoji = "🟢" if direction == "LONG" else "🔴"
                        entry = rec.get("entry_price", 0)
                        stop = rec.get("stop_price", 0)
                        await _send(
                            f"🔥🔥🔥 <b>FULL ALIGNMENT: {action} {self.symbol}</b>\n\n"
                            f"Grade: <b>{grade}</b> | Confidence: <b>{confidence}%</b>\n"
                            f"Entry: ₹{entry:,.2f} | Stop: ₹{stop:,.2f}\n"
                            f"Direction: <b>{direction}</b>\n\n"
                            f"Mode: <b>{settings.trading_mode}</b>"
                        )
                except Exception:
                    pass
            self._prev_alignment_level = level

            # Auto-execute on full alignment
            if s3_aligned:
                await self._process_signal(analysis)

            await self._broadcast_event("signal", {
                "symbol": self.symbol,
                "analysis": analysis,
                "alignment": self.alignment,
            })

        except Exception as e:
            logger.error("Signal evaluation failed for {}: {}", self.symbol, e)

    async def _process_signal(self, analysis: dict):
        """Process an actionable signal through risk gate and execution."""
        rec = analysis["recommendation"]
        action = rec["action"]
        confidence = rec["confidence"]
        entry_price = rec.get("entry_price", 0)
        stop_price = rec.get("stop_price", 0)
        grade = analysis.get("grade", "D")

        # Dedup: skip if same signal already processed (in-memory check)
        signal_key = f"{action}:{entry_price}:{stop_price}:{grade}"
        if signal_key == self._last_signal_key:
            return
        self._last_signal_key = signal_key

        # Dedup: also check DB for recent identical signal (survives restart)
        try:
            async with async_session() as session:
                recent = await db.load_recent_signals(session, self.instrument_id, limit=1)
                if recent:
                    last = recent[0]
                    if (last["entry_price"] == entry_price
                            and last["stop_price"] == stop_price
                            and last["direction"] == ("LONG" if action == "BUY" else "SHORT")):
                        logger.debug("Skipping duplicate signal for {}", self.symbol)
                        return
        except Exception:
            pass  # If DB check fails, proceed anyway

        # Risk gate: Circuit Breaker
        try:
            from app.risk.circuit_breaker import CircuitBreaker
            cb = CircuitBreaker({"max_portfolio_risk_pct": settings.max_portfolio_risk_pct})

            # Check for pending circuit breaker halt notification
            if hasattr(cb, '_pending_halt_notification') and cb._pending_halt_notification:
                reason, pct = cb._pending_halt_notification
                cb._pending_halt_notification = None
                try:
                    from app.notifications.telegram import notify_circuit_breaker
                    await notify_circuit_breaker(reason, pct)
                except Exception:
                    pass

            if entry_price and stop_price:
                risk_per_share = abs(entry_price - stop_price)
                # Position sizing
                from app.risk.position_sizer import PositionSizer
                ps = PositionSizer({"max_risk_per_trade_pct": settings.max_risk_per_trade_pct})
                sizing = ps.calculate_position_size(
                    entry_price=entry_price,
                    stop_price=stop_price,
                    account_equity=100000,  # Paper capital
                )
                if not sizing.get("is_valid", False):
                    logger.info("Signal rejected by position sizer: {}", sizing.get("reason"))
                    return
            else:
                sizing = {"shares": 0, "risk_amount": 0}
        except Exception as e:
            logger.warning("Risk gate error: {}", e)
            sizing = {"shares": 0, "risk_amount": 0}

        # Save signal to DB
        direction = "LONG" if action == "BUY" else "SHORT"
        try:
            async with async_session() as session:
                signal = await db.save_signal(session, {
                    "instrument_id": self.instrument_id,
                    "symbol": self.symbol,
                    "direction": direction,
                    "score": confidence,
                    "strategy": "TRIPLE_SCREEN",
                    "confirmations": analysis.get("validation", {}).get("warnings", []),
                    "entry_price": entry_price,
                    "stop_price": stop_price,
                    "status": "PENDING_CONFIRMATION" if settings.trading_mode == "LIVE" else "ACTIVE",
                })
        except Exception as e:
            logger.error("Signal DB save failed: {}", e)
            return

        # Execute or alert
        if settings.trading_mode == "PAPER" and sizing.get("shares", 0) > 0:
            await self._auto_execute(signal, sizing, analysis)
        else:
            # LIVE mode: just broadcast alert
            await self._broadcast_event("trade_alert", {
                "symbol": self.symbol,
                "action": action,
                "grade": grade,
                "confidence": confidence,
                "entry_price": entry_price,
                "stop_price": stop_price,
                "shares": sizing.get("shares", 0),
                "signal_id": signal.id,
            })

    async def _auto_execute(self, signal, sizing: dict, analysis: dict):
        """Auto-execute in paper mode."""
        rec = analysis["recommendation"]
        direction = "BUY" if rec["action"] == "BUY" else "SELL"
        entry = rec.get("entry_price", 0)
        stop = rec.get("stop_price", 0)
        shares = sizing.get("shares", 0)

        if shares <= 0 or entry <= 0:
            return

        try:
            async with async_session() as session:
                order = await db.save_order(session, {
                    "signal_id": signal.id,
                    "instrument_id": self.instrument_id,
                    "symbol": self.symbol,
                    "order_id": f"PIPE-{signal.id:04d}",
                    "direction": direction,
                    "order_type": "MARKET",
                    "quantity": shares,
                    "price": entry,
                    "status": "COMPLETE",
                    "mode": "PAPER",
                    "filled_price": entry,
                    "filled_quantity": shares,
                })

                pos_direction = "LONG" if direction == "BUY" else "SHORT"
                position = await db.save_position(session, {
                    "instrument_id": self.instrument_id,
                    "symbol": self.symbol,
                    "direction": pos_direction,
                    "entry_price": entry,
                    "quantity": shares,
                    "stop_price": stop,
                    "current_price": entry,
                    "risk_amount": sizing.get("risk_amount", 0),
                    "risk_percent": sizing.get("actual_risk_pct", 0),
                    "mode": "PAPER",
                })

            logger.info(
                "Auto-executed: {} {} x{} @ {:.2f} stop={:.2f}",
                direction, self.symbol, shares, entry, stop,
            )

            # Telegram trade notification
            try:
                from app.notifications.telegram import notify_trade
                await notify_trade(
                    self.symbol, direction, shares, entry, stop,
                    order.order_id, "PAPER", analysis.get("grade", "?"),
                )
            except Exception:
                pass

            await self._broadcast_event("order", {
                "symbol": self.symbol,
                "direction": direction,
                "quantity": shares,
                "price": entry,
                "order_id": order.order_id,
                "mode": "PAPER",
            })

        except Exception as e:
            logger.error("Auto-execute failed: {}", e)

    def _tf_to_screen(self, timeframe: str) -> Optional[int]:
        """Map timeframe back to screen number."""
        for screen, tf in self.screen_timeframes.items():
            if tf == timeframe:
                return int(screen)
        return None

    def _broadcast_running_bar(self):
        """Broadcast current running (in-progress) bars."""
        if not self._broadcast:
            return
        for tf, builder in self.candle_builders.items():
            bar = builder.running_bar
            if bar:
                self._schedule_async(self._broadcast_event("running_bar", {
                    "symbol": self.symbol,
                    "timeframe": tf,
                    "bar": bar,
                }))

    async def _broadcast_event(self, event_type: str, data: dict):
        """Broadcast a pipeline event to frontend."""
        if self._broadcast:
            await self._broadcast({"type": event_type, **data})

    def get_status(self) -> dict:
        """Get current session status."""
        candle_counts = {tf: len(df) for tf, df in self.candle_buffers.items()}

        # Determine data source
        source = "demo"
        for tf, df in self.candle_buffers.items():
            if not df.empty:
                source = "live"
                break

        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "token": self.token,
            "active": self.active,
            "instrument_id": self.instrument_id,
            "screen_timeframes": self.screen_timeframes,
            "candle_counts": candle_counts,
            "source": source,
            "has_analysis": self.latest_analysis is not None,
            "latest_grade": self.latest_analysis.get("grade") if self.latest_analysis else None,
            "latest_action": (
                self.latest_analysis.get("recommendation", {}).get("action")
                if self.latest_analysis else None
            ),
        }

    def get_trading_plan(self) -> dict:
        """Comprehensive trading plan with projected entries, stops, targets, P&L."""
        plan: dict = {
            "has_signal": False,
            "projected_entry": None,
            "projected_entry_type": None,
            "entry_price": None,
            "initial_stop": None,
            "trailing_stop": None,
            "targets": [],
            "risk_reward": None,
            "direction": None,
            "status": "WATCHING",  # WATCHING / ENTRY_PENDING / IN_TRADE / COMPLETED
        }

        a = self.latest_analysis
        al = self.alignment
        if not a:
            return plan

        rec = a.get("recommendation", {})
        s1 = a.get("screen1", {})
        s3 = a.get("screen3", {})
        tide = s1.get("tide")
        action = rec.get("action", "WAIT")
        entry = rec.get("entry_price")
        stop = rec.get("stop_price")
        grade = a.get("grade")

        # Get current price
        ltp = None
        screen2_tf = self.screen_timeframes.get("2", "1d")
        df = self.candle_buffers.get(screen2_tf, pd.DataFrame())
        if not df.empty:
            ltp = float(df.iloc[-1].get("close", 0))
        for tf, builder in self.candle_builders.items():
            bar = builder.running_bar
            if bar and bar.get("close"):
                ltp = bar["close"]
                break

        # Get SafeZone stops from indicators
        ind2 = self.indicators.get(screen2_tf, {})
        safezone_long = last_non_null(ind2.get("safezone_long", []))
        safezone_short = last_non_null(ind2.get("safezone_short", []))

        # Get previous bar high/low for entry calculation
        screen3_tf = self.screen_timeframes.get("3", "15m")
        df3 = self.candle_buffers.get(screen3_tf, pd.DataFrame())
        prev_high = float(df3.iloc[-2].get("high", 0)) if df3 is not None and len(df3) >= 2 else None
        prev_low = float(df3.iloc[-2].get("low", 0)) if df3 is not None and len(df3) >= 2 else None

        plan["direction"] = "LONG" if tide == "BULLISH" else "SHORT" if tide == "BEARISH" else None

        # ── Projected entry (when no actionable signal yet) ──
        if action == "WAIT" and tide:
            if tide == "BULLISH" and prev_high:
                plan["projected_entry"] = prev_high
                plan["projected_entry_type"] = "BUY_STOP"
                plan["initial_stop"] = safezone_long
                plan["status"] = "WATCHING"
            elif tide == "BEARISH" and prev_low:
                plan["projected_entry"] = prev_low
                plan["projected_entry_type"] = "SELL_STOP"
                plan["initial_stop"] = safezone_short
                plan["status"] = "WATCHING"

        # ── Active signal entry ──
        if action != "WAIT" and entry and stop:
            plan["has_signal"] = True
            plan["entry_price"] = entry
            plan["initial_stop"] = stop
            plan["status"] = "ENTRY_PENDING"

            # Trailing stop = current SafeZone (tightens as price moves)
            if action == "BUY" and safezone_long:
                plan["trailing_stop"] = safezone_long
            elif action == "SELL" and safezone_short:
                plan["trailing_stop"] = safezone_short

        # ── Targets (risk:reward 1:1, 1:2, 1:3) ──
        ent = plan.get("entry_price") or plan.get("projected_entry")
        stp = plan.get("initial_stop")
        if ent and stp and ent != stp:
            risk = abs(ent - stp)
            direction = plan["direction"]
            targets = []
            for rr in [1, 2, 3]:
                if direction == "LONG":
                    t = round(ent + risk * rr, 2)
                elif direction == "SHORT":
                    t = round(ent - risk * rr, 2)
                else:
                    t = None
                if t:
                    targets.append({"ratio": f"1:{rr}", "price": t, "reward": round(risk * rr, 2)})
            plan["targets"] = targets
            plan["risk_reward"] = f"Risk: {risk:.2f} per share"

        # ── P&L if in trade (check open positions) ──
        # This is simplified — real P&L comes from DB positions
        if ltp and ent:
            if plan["direction"] == "LONG":
                plan["unrealized_pnl_per_share"] = round(ltp - ent, 2)
            elif plan["direction"] == "SHORT":
                plan["unrealized_pnl_per_share"] = round(ent - ltp, 2)

        # Key levels summary
        plan["key_levels"] = {
            "ltp": ltp,
            "safezone_long": safezone_long,
            "safezone_short": safezone_short,
            "prev_high": prev_high,
            "prev_low": prev_low,
        }

        return plan

    def get_summary(self) -> dict:
        """Compact summary for command center dashboard."""
        ltp = None
        change_pct = None
        prev_close = None

        # Get LTP from the most recent candle buffer (screen 2 timeframe)
        screen2_tf = self.screen_timeframes.get("2", "1d")
        df = self.candle_buffers.get(screen2_tf, pd.DataFrame())
        if not df.empty:
            ltp = float(df.iloc[-1].get("close", 0))
            if len(df) >= 2:
                prev_close = float(df.iloc[-2].get("close", 0))
                if prev_close > 0:
                    change_pct = round((ltp - prev_close) / prev_close * 100, 2)

        # Check running bar for latest price
        for tf, builder in self.candle_builders.items():
            bar = builder.running_bar
            if bar and bar.get("close"):
                ltp = bar["close"]
                break

        # Extract analysis
        a = self.latest_analysis
        s1 = a.get("screen1", {}) if a else {}
        s2 = a.get("screen2", {}) if a else {}
        rec = a.get("recommendation", {}) if a else {}

        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "ltp": ltp,
            "prev_close": prev_close,
            "change_pct": change_pct,
            "tide": s1.get("tide"),
            "ema_trend": s1.get("ema_trend"),
            "impulse": s1.get("impulse_signal"),
            "wave_signal": s2.get("signal"),
            "action": rec.get("action"),
            "grade": a.get("grade") if a else None,
            "confidence": rec.get("confidence"),
            "entry_price": rec.get("entry_price"),
            "stop_price": rec.get("stop_price"),
            "active": self.active,
            "screen_timeframes": self.screen_timeframes,
            "alignment": self.alignment,
        }

    def stop(self):
        """Stop tracking this asset."""
        self.active = False
        self.candle_builders.clear()
        logger.info("AssetSession stopped: {}:{}", self.symbol, self.exchange)
