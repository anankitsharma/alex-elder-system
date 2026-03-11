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
        """Process incoming tick — route to all candle builders."""
        if not self.active:
            return

        for tf, builder in self.candle_builders.items():
            completed = builder.on_tick(tick)
            if completed:
                # Schedule async handler
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(self._on_new_candle(tf, completed))
                except RuntimeError:
                    pass

        # Broadcast running bar for display
        self._broadcast_running_bar()

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

        # Evaluate signals
        await self._evaluate_signals()

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

            # Check if actionable signal
            action = analysis.get("recommendation", {}).get("action", "WAIT")
            confidence = analysis.get("recommendation", {}).get("confidence", 0)
            grade = analysis.get("grade", "D")

            if action != "WAIT" and confidence >= settings.min_signal_score:
                await self._process_signal(analysis)

            await self._broadcast_event("signal", {
                "symbol": self.symbol,
                "analysis": analysis,
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
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(self._broadcast_event("running_bar", {
                            "symbol": self.symbol,
                            "timeframe": tf,
                            "bar": bar,
                        }))
                except RuntimeError:
                    pass

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

    def stop(self):
        """Stop tracking this asset."""
        self.active = False
        self.candle_builders.clear()
        logger.info("AssetSession stopped: {}:{}", self.symbol, self.exchange)
