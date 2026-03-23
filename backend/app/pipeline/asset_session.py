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
from app.pipeline.market_hours import get_session as get_market_session
from app.pipeline.utils import last_non_null, slope_of_last, trend_of_last
from app.pipeline import db_persistence as db
from app.trading.executor import TradeExecutor, ExitReason
from app.trading.paper import PaperPlacer


# ── Alert State Manager ──────────────────────────────────────
# Prevents alert spam from alignment oscillation, repeated signals,
# and noise near decision boundaries.
#
# Design principles (from freqtrade, jesse-ai, TradingView alerts):
#   1. Cooldown: Don't re-alert same level+direction within N minutes
#   2. Hysteresis: Require alignment to persist N consecutive evals before firing
#   3. Direction-aware: BULLISH S1 alert doesn't suppress BEARISH S1 alert
#   4. Signal dedup: Same direction within cooldown = duplicate (ignore price)
#   5. Flip detection: Direction change always alerts (no cooldown)

class AlertStateManager:
    """Tracks alert state to prevent spam while allowing legitimate alerts.

    Anti-spam features:
      1. Cooldown: Don't re-alert same level+direction within N minutes
      2. Hysteresis: Require alignment to persist N consecutive evals before firing
      3. Direction-aware: BULLISH S1 alert doesn't suppress BEARISH S1 alert
      4. Signal dedup: Same direction within cooldown = duplicate (ignore price)
      5. Flip confirmation: Direction change requires N consecutive bars to confirm
      6. Wave confirmation: Wave signal must persist N bars before alignment counts
    """

    # Cooldown in seconds per alignment level
    COOLDOWNS = {
        1: 30 * 60,    # Screen 1 (tide): 30 min cooldown
        2: 15 * 60,    # Screen 1+2 (tide+wave): 15 min cooldown
        3: 10 * 60,    # Full alignment: 10 min cooldown
    }

    # Consecutive evaluations required before alerting (hysteresis)
    CONFIRM_COUNT = {
        1: 2,  # Screen 1: must persist 2 consecutive evals
        2: 1,  # Screen 1+2: immediate (wave already filtered by Screen 1)
        3: 1,  # Full alignment: immediate (already confirmed by Screen 1+2)
    }

    # Signal execution cooldown (same direction, regardless of price)
    SIGNAL_COOLDOWN = 30 * 60  # 30 minutes

    def __init__(self, config: Optional[dict] = None):
        config = config or {}
        self._flip_confirm_bars: int = config.get(
            "flip_confirm_bars", settings.flip_confirm_bars
        )
        self._wave_confirm_bars: int = config.get(
            "wave_confirm_bars", settings.wave_confirm_bars
        )

        # Last alert timestamp per (level, direction) — for cooldown
        self._last_alert: dict[str, float] = {}  # "level:direction" -> epoch

        # Consecutive alignment counter per level — for hysteresis
        self._consecutive: dict[int, int] = {1: 0, 2: 0, 3: 0}

        # Previous alignment state — for tracking transitions
        self._prev_level: int = 0
        self._prev_direction: Optional[str] = None

        # Last signal execution per direction — for signal dedup
        self._last_signal_time: dict[str, float] = {}  # "LONG"/"SHORT" -> epoch

        # Flip confirmation state — requires N consecutive bars of new direction
        # _established_direction is the direction of the last confirmed alert
        # _flip_direction/_flip_counter track the pending (unconfirmed) new direction
        self._established_direction: Optional[str] = None
        self._flip_counter: int = 0
        self._flip_direction: Optional[str] = None

        # Wave confirmation state — requires N consecutive same-direction readings
        self._wave_state: Optional[str] = None       # Last confirmed wave
        self._wave_pending: Optional[str] = None      # Pending wave direction
        self._wave_confirm_count: int = 0

    def check_alignment_alert(
        self, level: int, direction: Optional[str], now: Optional[float] = None,
    ) -> bool:
        """Check if an alignment alert should fire.

        Returns True if alert should be sent, False if suppressed.
        Updates internal state. Direction flips require sustained confirmation.
        """
        import time as _t
        now = now or _t.time()

        if level <= 0 or direction is None:
            # Alignment lost — reset consecutive counter for this level
            for lv in range(1, 4):
                if lv > level:
                    self._consecutive[lv] = 0
            self._prev_level = level
            self._prev_direction = direction
            # Reset flip tracking when alignment drops to 0
            if level <= 0:
                self._flip_counter = 0
                self._flip_direction = None
            return False

        # ── Flip confirmation: require N consecutive bars of new direction ──
        is_confirmed_flip = False
        if (self._established_direction is not None
                and direction != self._established_direction
                and self._prev_level > 0):
            # Direction differs from established — count consecutive bars
            if self._flip_direction == direction:
                self._flip_counter += 1
            else:
                # Different pending direction — restart count
                self._flip_direction = direction
                self._flip_counter = 1

            if self._flip_counter >= self._flip_confirm_bars:
                is_confirmed_flip = True
                self._flip_counter = 0
                self._flip_direction = None
        elif direction == self._established_direction:
            # Returned to established direction — reset flip tracking
            self._flip_counter = 0
            self._flip_direction = None

        # Update consecutive counter
        if level >= self._prev_level:
            self._consecutive[level] = self._consecutive.get(level, 0) + 1
        else:
            # Level dropped — reset higher levels
            for lv in range(level + 1, 4):
                self._consecutive[lv] = 0

        should_alert = False
        alert_key = f"{level}:{direction}"

        if level > self._prev_level or is_confirmed_flip:
            # Level increased or confirmed direction flip — candidate for alert

            # Check hysteresis (must persist N evals)
            required = self.CONFIRM_COUNT.get(level, 1)
            if self._consecutive.get(level, 0) >= required or is_confirmed_flip:
                # Check cooldown (confirmed flips still respect cooldown)
                cooldown = self.COOLDOWNS.get(level, 600)
                last = self._last_alert.get(alert_key, 0)
                if now - last >= cooldown:
                    should_alert = True
                    self._last_alert[alert_key] = now
                    self._established_direction = direction

        # Set established direction on first alert (level increase from 0)
        if self._established_direction is None and level > 0:
            if self._consecutive.get(level, 0) >= self.CONFIRM_COUNT.get(level, 1):
                self._established_direction = direction
                should_alert = True
                self._last_alert[alert_key] = now

        self._prev_level = level
        self._prev_direction = direction
        return should_alert

    def check_wave_confirmed(self, wave_signal: Optional[str]) -> Optional[str]:
        """Filter wave signal through confirmation requirement.

        Requires wave_confirm_bars consecutive same-direction readings
        before acknowledging the wave. Returns the confirmed wave or None.
        """
        if wave_signal is None:
            self._wave_pending = None
            self._wave_confirm_count = 0
            return self._wave_state

        if wave_signal == self._wave_pending:
            self._wave_confirm_count += 1
        else:
            self._wave_pending = wave_signal
            self._wave_confirm_count = 1

        if self._wave_confirm_count >= self._wave_confirm_bars:
            self._wave_state = wave_signal

        return self._wave_state

    def check_signal_dedup(self, direction: str, now: Optional[float] = None) -> bool:
        """Check if a signal execution should proceed.

        Returns True if signal is new (not duplicate), False if suppressed.
        Deduplicates by direction + time window (ignores price changes).
        """
        import time as _t
        now = now or _t.time()

        last = self._last_signal_time.get(direction, 0)
        if now - last < self.SIGNAL_COOLDOWN:
            return False  # Too soon — duplicate

        self._last_signal_time[direction] = now
        return True

    def reset(self):
        """Reset all state (e.g., on session restart)."""
        self._last_alert.clear()
        self._consecutive = {1: 0, 2: 0, 3: 0}
        self._prev_level = 0
        self._prev_direction = None
        self._last_signal_time.clear()
        self._established_direction = None
        self._flip_counter = 0
        self._flip_direction = None
        self._wave_state = None
        self._wave_pending = None
        self._wave_confirm_count = 0


class AssetSession:
    """Manages the full pipeline for a single asset."""

    def __init__(self, symbol: str, exchange: str, token: str, user_id: Optional[int] = None):
        self.symbol = symbol
        self.exchange = exchange
        self.token = token
        self.user_id = user_id  # None = legacy single-user mode
        self._asset_trading_mode: Optional[str] = None  # Per-asset override (PAPER/LIVE)
        self.instrument_id: Optional[int] = None
        self.active = False
        self.contract_symbol: Optional[str] = None  # e.g. "NIFTY30MAR26FUT"
        self.expiry_date: Optional[datetime] = None  # Contract expiry
        self.days_to_expiry: Optional[int] = None

        # Candle buffers per timeframe: "1d" -> DataFrame
        self.candle_buffers: dict[str, pd.DataFrame] = {}

        # CandleBuilder per intraday timeframe
        self.candle_builders: dict[str, CandleBuilder] = {}

        # Latest indicator results per timeframe
        self.indicators: dict[str, dict] = {}

        # Latest Triple Screen analysis
        self.latest_analysis: Optional[dict] = None

        # Alert state manager — prevents spam from oscillation/noise
        # Handles: cooldowns, hysteresis, direction-aware dedup, flip confirmation, wave confirmation
        self._alert_mgr = AlertStateManager()

        # Exit dedup — prevents duplicate stop/target notifications per position
        self._exit_initiated: set[int] = set()

        # Alignment tracking for progressive alerts
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

        # Per-symbol lock to prevent concurrent signal processing / stop checks
        self._signal_lock = asyncio.Lock()

        # Singleton circuit breaker — persists across signals, synced from DB
        from app.risk.circuit_breaker import CircuitBreaker
        self._circuit_breaker = CircuitBreaker({
            "max_portfolio_risk_pct": settings.max_portfolio_risk_pct,
        })

        # Kill switch — set by PipelineManager to block all signal processing
        self._kill_switch = False

        # Candle counter for periodic reconciliation
        self._candle_count: int = 0

        # Trade executor — unified state machine for trade lifecycle
        self._init_executor()

    @property
    def effective_trading_mode(self) -> str:
        """Resolve trading mode: per-asset override > global default."""
        if self._asset_trading_mode:
            return self._asset_trading_mode
        return settings.trading_mode

    def _init_executor(self):
        """Initialize the TradeExecutor with the appropriate placer for the trading mode."""
        if self.effective_trading_mode == "LIVE":
            from app.trading.live import LivePlacer
            placer = LivePlacer()
        else:
            placer = PaperPlacer(slippage_pct=settings.paper_slippage_pct)
        self.executor = TradeExecutor(placer, on_notify=self._on_executor_event)

    def _on_executor_event(self, event: str, data: dict):
        """Callback for TradeExecutor events — log for now."""
        logger.info("Executor event [{}]: {} {}", self.symbol, event, data)

    async def _init_circuit_breaker(self):
        """Sync circuit breaker from DB — load month start equity + realized losses."""
        try:
            from datetime import date as _date
            async with async_session() as session:
                month_start = await db.get_month_start_equity(session, user_id=self.user_id or 1)
                self._circuit_breaker.set_month_start_equity(month_start)

                # Sync realized losses from this month's trades
                month_str = _date.today().strftime("%Y-%m")
                month_trades = await db.load_month_trades(session, month_str)
                self._circuit_breaker.sync_from_db(month_trades)
                logger.info(
                    "Circuit breaker initialized: month_start={:.2f} losses={:.2f}",
                    month_start, self._circuit_breaker.realized_losses,
                )
        except Exception as e:
            logger.warning("Circuit breaker init failed, using defaults: {}", e)

    async def _recover_state(self):
        """Recover orphaned positions and orders from previous session (crash recovery).

        1. Load per-asset trading mode from DB
        2. Load OPEN positions from DB → populate _exit_initiated and CB open risk
        3. Cancel stale PENDING orders (>1h old in PAPER mode)
        4. Sync executor with recovered positions
        """
        try:
            import time as _t
            async with async_session() as session:
                # Load per-asset trading mode if user_id is set
                if self.user_id:
                    from sqlalchemy import select as _sel
                    from app.models.user import UserAssetSettings
                    stmt = _sel(UserAssetSettings).where(
                        UserAssetSettings.user_id == self.user_id,
                        UserAssetSettings.symbol == self.symbol,
                        UserAssetSettings.exchange == self.exchange,
                    )
                    asset_result = await session.execute(stmt)
                    asset_cfg = asset_result.scalar_one_or_none()
                    if asset_cfg:
                        self._asset_trading_mode = asset_cfg.trading_mode
                        logger.info(
                            "Loaded per-asset mode for {} {}: {}",
                            self.symbol, self.user_id, self._asset_trading_mode,
                        )
                        # Re-init executor with correct mode
                        self._init_executor()

            async with async_session() as session:
                # 1. Recover open positions
                positions = await db.load_open_positions_by_symbol(session, self.symbol)
                if positions:
                    open_risk_positions = []
                    for pos in positions:
                        open_risk_positions.append({
                            "entry_price": pos.entry_price,
                            "stop_price": pos.stop_price or 0,
                            "shares": pos.quantity,
                            "direction": "BUY" if pos.direction == "LONG" else "SELL",
                        })
                    # Update circuit breaker with open risk
                    self._circuit_breaker.update_open_positions(open_risk_positions)
                    logger.info(
                        "Recovered {} open positions for {} (CB open risk updated)",
                        len(positions), self.symbol,
                    )

                # 2. Handle stale PENDING orders
                pending = await db.load_pending_orders(session)
                stale_count = 0
                for order in pending:
                    if order.symbol != self.symbol:
                        continue
                    # In PAPER mode, cancel orders older than 1 hour
                    if (order.mode or self.effective_trading_mode) == "PAPER":
                        if order.created_at:
                            age = _t.time() - order.created_at.timestamp()
                            if age > 3600:  # 1 hour
                                order.status = "CANCELLED"
                                stale_count += 1
                if stale_count:
                    await session.commit()
                    logger.info("Cancelled {} stale PENDING orders for {}", stale_count, self.symbol)

        except Exception as e:
            logger.warning("State recovery failed for {}: {}", self.symbol, e)

    async def _reconcile_state(self):
        """Periodic check: compare executor in-memory state with DB positions.

        Detects divergence (e.g., position closed in DB but still open in executor).
        Logs warnings on mismatch — does NOT auto-fix (requires manual review).
        """
        try:
            async with async_session() as session:
                db_positions = await db.load_open_positions_by_symbol(session, self.symbol)

            db_open_count = len(db_positions)
            exec_pos = self.executor.get_position(self.symbol)
            exec_has_open = exec_pos is not None and exec_pos.is_open if exec_pos else False

            # Check for divergence
            if db_open_count > 0 and not exec_has_open:
                logger.warning(
                    "STATE DIVERGENCE: {} has {} open positions in DB but executor shows none",
                    self.symbol, db_open_count,
                )
            elif db_open_count == 0 and exec_has_open:
                logger.warning(
                    "STATE DIVERGENCE: {} executor has open position but DB shows none",
                    self.symbol,
                )
        except Exception as e:
            logger.debug("Reconciliation check failed for {}: {}", self.symbol, e)

    async def start(self):
        """Initialize session: resolve instrument, load history, compute indicators."""
        logger.info("Starting AssetSession for {}:{}", self.symbol, self.exchange)

        # Resolve instrument in DB
        async with async_session() as session:
            inst = await db.get_or_create_instrument(
                session, self.symbol, self.exchange, self.token
            )
            self.instrument_id = inst.id

        # Initialize circuit breaker from DB
        await self._init_circuit_breaker()

        # Resolve contract expiry from scrip master
        await self._resolve_expiry()

        # Determine screen timeframes based on asset class
        await self._resolve_timeframes()

        # Load historical data for all screen timeframes
        await self._load_historical()

        # Create candle builders for intraday timeframes
        for screen, tf in self.screen_timeframes.items():
            if tf not in ("1w",):  # Weekly is resampled from daily
                self.candle_builders[tf] = CandleBuilder(
                    tf, on_bar_close=self._on_bar_close_sync,
                    exchange=self.exchange, symbol=self.symbol,
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

        # Recover orphaned positions/orders from previous session
        await self._recover_state()

        # Run initial analysis
        await self._evaluate_signals()

        self.active = True
        logger.info(
            "AssetSession ready: {}:{} | screens: {} | candles: {}",
            self.symbol, self.exchange, self.screen_timeframes,
            {tf: len(df) for tf, df in self.candle_buffers.items()},
        )

        await self._broadcast_event("pipeline_status", self.get_status())

    async def _resolve_expiry(self):
        """Resolve contract symbol and expiry date from scrip master."""
        try:
            from app.broker.instruments import download_scrip_master
            scrip_df = await download_scrip_master()
            match = scrip_df[scrip_df["token"] == self.token]
            if not match.empty:
                row = match.iloc[0]
                self.contract_symbol = row.get("symbol", "")
                expiry_str = row.get("expiry", "")
                if expiry_str:
                    self.expiry_date = datetime.strptime(str(expiry_str), "%d%b%Y")
                    self.days_to_expiry = (self.expiry_date - datetime.now()).days
                    logger.info("Contract: {} expiry={} ({}d left)",
                                self.contract_symbol, self.expiry_date.strftime("%Y-%m-%d"),
                                self.days_to_expiry)
        except Exception as e:
            logger.warning("Expiry resolution failed for {}: {}", self.symbol, e)

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
                    await db.save_candles(session, self.instrument_id, timeframe, candle_dicts, self.token)
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

        # Rolling window: keep max 500 bars per timeframe to bound memory
        MAX_BUFFER_BARS = 500
        if timeframe in self.candle_buffers and not self.candle_buffers[timeframe].empty:
            buf = pd.concat(
                [self.candle_buffers[timeframe], new_row], ignore_index=True
            )
            if len(buf) > MAX_BUFFER_BARS:
                buf = buf.iloc[-MAX_BUFFER_BARS:]
            self.candle_buffers[timeframe] = buf
        else:
            self.candle_buffers[timeframe] = new_row

        # Persist to DB
        try:
            async with async_session() as session:
                await db.save_candles(session, self.instrument_id, timeframe, [candle], self.token)
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

        # Periodic state reconciliation (every 10 candles)
        self._candle_count += 1
        if self._candle_count % 10 == 0:
            await self._reconcile_state()

    async def _check_stop_losses(self, current_price: float):
        """Check if any open position's stop or target has been hit. Close if so."""
        if not self._signal_lock.locked():
            async with self._signal_lock:
                return await self._check_stop_losses_inner(current_price)
        else:
            # Lock held by signal evaluation — skip this check
            return

    async def _check_stop_losses_inner(self, current_price: float):
        """Inner stop/target check (called under lock)."""
        if current_price <= 0:
            return
        try:
            async with async_session() as session:
                positions = await db.load_open_positions_by_symbol(session, self.symbol)
                for pos in positions:
                    # Skip if exit already initiated for this position
                    if pos.id in self._exit_initiated:
                        continue

                    # Track MAE/MFE (Maximum Adverse/Favorable Excursion)
                    if pos.direction == "LONG":
                        excursion = current_price - pos.entry_price
                    else:
                        excursion = pos.entry_price - current_price

                    # Update MAE (most negative excursion = worst drawdown during trade)
                    if excursion < (pos.mae or 0):
                        pos.mae = round(excursion, 2)
                    # Update MFE (most positive excursion = best profit during trade)
                    if excursion > (pos.mfe or 0):
                        pos.mfe = round(excursion, 2)

                    # Update current_price for mark-to-market (real-time P&L)
                    pos.current_price = current_price
                    # Compute unrealized P&L
                    if pos.direction == "LONG":
                        pos.unrealized_pnl = round((current_price - pos.entry_price) * pos.quantity, 2)
                    else:
                        pos.unrealized_pnl = round((pos.entry_price - current_price) * pos.quantity, 2)

                    exit_reason = None
                    # Check stop loss
                    if pos.stop_price and pos.stop_price > 0:
                        if pos.direction == "LONG" and current_price <= pos.stop_price:
                            exit_reason = "STOP_LOSS"
                        elif pos.direction == "SHORT" and current_price >= pos.stop_price:
                            exit_reason = "STOP_LOSS"

                    # Check target price (2:1 R:R)
                    if not exit_reason and pos.target_price and pos.target_price > 0:
                        if pos.direction == "LONG" and current_price >= pos.target_price:
                            exit_reason = "TARGET"
                        elif pos.direction == "SHORT" and current_price <= pos.target_price:
                            exit_reason = "TARGET"

                    if exit_reason:
                        # Mark exit as initiated to prevent duplicate processing
                        self._exit_initiated.add(pos.id)
                        # Place live exit order if in LIVE mode
                        if pos.mode == "LIVE":
                            try:
                                from app.trading.live import LivePlacer
                                placer = LivePlacer()
                                exit_dir = "SELL" if pos.direction == "LONG" else "BUY"
                                result = await placer.place_exit(
                                    symbol=self.symbol, token=self.token,
                                    exchange=self.exchange, direction=exit_dir,
                                    quantity=pos.quantity, order_type="MARKET",
                                    price=current_price, product_type="CARRYFORWARD",
                                )
                                if result.status == "REJECTED":
                                    logger.error(
                                        "LIVE exit REJECTED for {} {}: {}",
                                        self.symbol, exit_reason, result.message,
                                    )
                                    continue  # Don't close in DB if broker rejected
                                logger.info(
                                    "[LIVE] Exit order placed: {} {} order={}",
                                    exit_dir, self.symbol, result.order_id,
                                )
                            except Exception as e:
                                logger.error("LIVE exit order failed for {}: {}", self.symbol, e)
                                continue  # Don't close DB position if broker call failed

                        trade = await db.close_position(session, pos.id, current_price)
                        if trade:
                            pnl = (current_price - pos.entry_price) * pos.quantity if pos.direction == "LONG" \
                                else (pos.entry_price - current_price) * pos.quantity

                            # Update account equity + circuit breaker
                            try:
                                await db.update_portfolio_equity(session, pnl, user_id=self.user_id or 1)
                                if pnl < 0:
                                    self._circuit_breaker.record_loss(abs(pnl))
                            except Exception:
                                pass

                            label = "STOP HIT" if exit_reason == "STOP_LOSS" else "TARGET HIT"
                            logger.info(
                                "{}: {} {} closed @ {:.2f} (stop={:.2f}, target={}) P&L={:.2f}",
                                label, pos.direction, self.symbol, current_price,
                                pos.stop_price or 0, pos.target_price or 0, pnl,
                            )
                            await self._broadcast_event("position_closed", {
                                "symbol": self.symbol,
                                "direction": pos.direction,
                                "entry_price": pos.entry_price,
                                "exit_price": current_price,
                                "stop_price": pos.stop_price,
                                "target_price": pos.target_price,
                                "quantity": pos.quantity,
                                "pnl": round(pnl, 2),
                                "reason": exit_reason,
                            })
                            # Notification
                            try:
                                from app.notifications.telegram import notify_position_closed
                                await notify_position_closed(
                                    symbol=self.symbol,
                                    direction=pos.direction,
                                    entry_price=pos.entry_price,
                                    exit_price=current_price,
                                    quantity=pos.quantity,
                                    pnl=round(pnl, 2),
                                    reason=exit_reason,
                                    stop_price=pos.stop_price or 0,
                                    target_price=pos.target_price or 0,
                                    mode=pos.mode or settings.trading_mode,
                                )
                            except Exception:
                                pass
                # Broadcast portfolio update for real-time dashboard
                total_unrealized = sum(
                    (current_price - p.entry_price) * p.quantity if p.direction == "LONG"
                    else (p.entry_price - current_price) * p.quantity
                    for p in positions
                )
                await self._broadcast_event("portfolio_update", {
                    "symbol": self.symbol,
                    "unrealized_pnl": round(total_unrealized, 2),
                    "position_count": len(positions),
                })

                await session.commit()  # Persist MAE/MFE + mark-to-market updates
        except Exception as e:
            logger.debug("Stop/target check failed for {}: {}", self.symbol, e)

    async def _update_trailing_stops(self):
        """Update open position stops using SafeZone (Elder's trailing stop method).

        Skips outside market hours to avoid setting stops on stale data.

        Rules:
        - LONG: stop = max(current_stop, new_safezone_long) — only tightens up
        - SHORT: stop = min(current_stop, new_safezone_short) — only tightens down
        - Never widens the stop
        """
        try:
            from app.pipeline.market_hours import is_market_open
            if not is_market_open(self.exchange, self.symbol):
                return

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
                        # Also update executor's in-memory stop
                        self.executor.update_stop(self.symbol, new_stop)
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
        """Run Triple Screen analysis on latest indicator data (under lock).

        Skips evaluation outside market hours (weekends, holidays, off-hours)
        to prevent signals firing on stale data.
        """
        from app.pipeline.market_hours import is_market_open
        if not is_market_open(self.exchange, self.symbol):
            return
        async with self._signal_lock:
            await self._evaluate_signals_inner()

    async def _evaluate_signals_inner(self):
        """Inner signal evaluation (called under lock)."""
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

            # Skip analysis if any screen has insufficient data
            if ind1.get("insufficient_data") or ind2.get("insufficient_data"):
                logger.debug(
                    "Skipping analysis for {}: insufficient indicator data",
                    self.symbol,
                )
                return

            # Screen 1: Trend — apply dead zone to MACD-H slope
            raw_slope = slope_of_last(ind1.get("macd_histogram", []))
            clamped_slope = 0 if (raw_slope is not None
                                  and abs(raw_slope) < settings.tide_dead_zone) else raw_slope
            screen1 = {
                "macd_histogram_slope": clamped_slope,
                "impulse_signal": last_non_null(ind1.get("impulse_signal", []), "neutral"),
                "ema_trend": trend_of_last(ind1.get("ema13", [])),
            }

            # Screen 2: Oscillator — apply dead zone to Force Index(2)
            raw_fi2 = last_non_null(ind2.get("force_index_2", []))
            clamped_fi2 = 0 if (raw_fi2 is not None
                                and abs(raw_fi2) < settings.wave_fi2_dead_zone) else raw_fi2
            screen2 = {
                "force_index_2": clamped_fi2,
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
                if last_close <= 0:
                    screen2["value_zone_position"] = None
                else:
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
            raw_wave = s2_data.get("signal")
            action = rec.get("action", "WAIT")
            confidence = rec.get("confidence", 0)
            grade = analysis.get("grade", "D")

            # Filter wave through confirmation (requires N consecutive same readings)
            wave = self._alert_mgr.check_wave_confirmed(raw_wave)

            # ── ADX regime filter: reduce confidence in sideways markets ──
            # Skip filter if ADX is not available or 0 (insufficient data)
            adx_value = None
            if settings.adx_filter_enabled:
                screen1_tf = self.screen_timeframes.get("1", "1w")
                adx_list = self.indicators.get(screen1_tf, {}).get("adx", [])
                adx_value = last_non_null(adx_list)
                if adx_value and adx_value > 0:  # Only filter when ADX is actually computed
                    if adx_value < settings.adx_weak_trend:
                        # Sideways market — suppress signal
                        confidence = 0
                    elif adx_value < settings.adx_moderate_trend:
                        # Weak trend — reduce confidence by 25%
                        confidence = int(confidence * 0.75)

            # Screen 1 aligned = tide is clear (not neutral)
            s1_aligned = tide in ("BULLISH", "BEARISH")
            # Screen 2 aligned = confirmed wave signal matches tide direction
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

            # ── Progressive alignment alerts (with anti-spam) ──
            # AlertStateManager handles: cooldowns, hysteresis, direction flips,
            # and oscillation suppression (tide toggling near boundary)
            should_alert = self._alert_mgr.check_alignment_alert(level, direction)

            if should_alert:
                try:
                    from app.notifications.telegram import _send, Priority
                    if level == 1:
                        await _send(
                            f"📊 <b>{self.symbol}</b> — Screen 1 aligned\n"
                            f"Tide: <b>{tide}</b> | Direction: {direction}\n"
                            f"Watching for Screen 2 confirmation...",
                            priority=Priority.LOW,
                        )
                    elif level == 2:
                        await _send(
                            f"{'🟢' if direction == 'LONG' else '🔴'} <b>{self.symbol}</b> — Tide + Wave ALIGNED\n"
                            f"Direction: <b>{direction}</b>\n"
                            f"Tide: {tide} | Wave: {wave}\n"
                            f"⏳ Waiting for entry trigger (Screen 3)...",
                            priority=Priority.NORMAL,
                            discord_color="buy" if direction == "LONG" else "sell",
                        )
                    elif level == 3:
                        entry = rec.get("entry_price", 0)
                        stop = rec.get("stop_price", 0)
                        await _send(
                            f"🔥🔥🔥 <b>FULL ALIGNMENT: {action} {self.symbol}</b>\n\n"
                            f"Grade: <b>{grade}</b> | Confidence: <b>{confidence}%</b>\n"
                            f"Entry: ₹{entry:,.2f} | Stop: ₹{stop:,.2f}\n"
                            f"Direction: <b>{direction}</b>\n\n"
                            f"Mode: <b>{settings.trading_mode}</b>",
                            priority=Priority.HIGH,
                            discord_color="buy" if action == "BUY" else "sell",
                        )
                except Exception:
                    pass

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
        if self._kill_switch:
            logger.warning("Signal blocked — kill switch active for {}", self.symbol)
            return

        rec = analysis["recommendation"]
        action = rec["action"]
        confidence = rec["confidence"]
        entry_price = rec.get("entry_price", 0)
        stop_price = rec.get("stop_price", 0)
        grade = analysis.get("grade", "D")

        # Position-aware dedup: suppress same-direction signal if already in position
        # Also check total portfolio margin — reject if already over-leveraged
        direction = "LONG" if action == "BUY" else "SHORT"
        try:
            async with async_session() as session:
                open_positions = await db.load_open_positions_by_symbol(session, self.symbol)
                for pos in open_positions:
                    if pos.direction == direction:
                        logger.debug(
                            "Signal suppressed: already {} {} (position {})",
                            direction, self.symbol, pos.id,
                        )
                        return

                # Total portfolio margin check — reject if already using > 80% of equity
                from app.models.trade import Position as PositionModel
                from sqlalchemy import select as _sel
                all_open = await session.execute(
                    _sel(PositionModel).where(PositionModel.status == "OPEN")
                )
                total_notional = sum(
                    abs(p.quantity * p.entry_price) for p in all_open.scalars().all()
                )
                equity = await db.get_current_equity(session, user_id=self.user_id or 1)
                if equity > 0 and total_notional > equity * 0.8:
                    logger.info(
                        "Signal rejected: total margin {:.0f} > 80% of equity {:.0f}",
                        total_notional, equity,
                    )
                    return
        except Exception:
            pass  # If checks fail, proceed anyway

        # Revenge trading prevention: block after N consecutive losses
        try:
            async with async_session() as session:
                from sqlalchemy import select
                from app.models.trade import Trade
                stmt = (
                    select(Trade)
                    .where(Trade.symbol == self.symbol)
                    .order_by(Trade.created_at.desc())
                    .limit(settings.max_consecutive_losses)
                )
                if self.user_id:
                    stmt = stmt.where(Trade.user_id == self.user_id)
                result = await session.execute(stmt)
                recent_trades = result.scalars().all()

                if len(recent_trades) >= settings.max_consecutive_losses:
                    all_losses = all(t.pnl < 0 for t in recent_trades)
                    if all_losses and recent_trades:
                        import time as _t
                        last_loss_time = recent_trades[0].created_at.timestamp() if recent_trades[0].created_at else 0
                        cooldown_remaining = (settings.loss_cooldown_minutes * 60) - (_t.time() - last_loss_time)
                        if cooldown_remaining > 0:
                            logger.info(
                                "Revenge prevention: {} consecutive losses for {} — locked out for {:.0f}min",
                                len(recent_trades), self.symbol, cooldown_remaining / 60,
                            )
                            return
        except Exception:
            pass

        # Dedup: direction + time-based (ignores small price changes)
        # AlertStateManager enforces 30-min cooldown per direction
        direction = "LONG" if action == "BUY" else "SHORT"
        if not self._alert_mgr.check_signal_dedup(direction):
            logger.debug("Signal suppressed by cooldown for {} ({})", self.symbol, direction)
            return

        # Dedup: also check DB for recent identical signal (survives restart)
        try:
            async with async_session() as session:
                recent = await db.load_recent_signals(session, self.instrument_id, limit=1)
                if recent:
                    last = recent[0]
                    if last["direction"] == direction:
                        # Same direction — check if within cooldown window
                        from datetime import datetime as _dt
                        last_ts = last.get("created_at") or last.get("timestamp")
                        if last_ts:
                            if isinstance(last_ts, str):
                                try:
                                    last_time = _dt.fromisoformat(last_ts)
                                except ValueError:
                                    last_time = None
                            else:
                                last_time = last_ts
                            if last_time:
                                import time as _t
                                elapsed = _t.time() - last_time.timestamp()
                                if elapsed < AlertStateManager.SIGNAL_COOLDOWN:
                                    logger.debug("Skipping duplicate signal for {} (DB cooldown)", self.symbol)
                                    return
        except Exception:
            pass  # If DB check fails, proceed anyway

        # Risk gate: Circuit Breaker (singleton, persisted)
        try:
            cb = self._circuit_breaker

            # Check for pending circuit breaker halt notification
            if hasattr(cb, '_pending_halt_notification') and cb._pending_halt_notification:
                reason, pct = cb._pending_halt_notification
                cb._pending_halt_notification = None
                try:
                    from app.notifications.telegram import notify_circuit_breaker
                    await notify_circuit_breaker(reason, pct)
                except Exception:
                    pass

            # Check if trading is halted
            cb_status = cb.check_can_trade()
            if not cb_status.get("is_allowed", True):
                logger.info("Signal blocked by circuit breaker: {}", cb_status.get("halt_reason"))
                return

            if entry_price and stop_price:
                risk_per_share = abs(entry_price - stop_price)

                # Get real account equity from DB
                async with async_session() as session:
                    account_equity = await db.get_current_equity(session, user_id=self.user_id or 1)

                # Position sizing with real equity
                from app.risk.position_sizer import PositionSizer
                ps = PositionSizer({"max_risk_per_trade_pct": settings.max_risk_per_trade_pct})
                sizing = ps.calculate_position_size(
                    entry_price=entry_price,
                    stop_price=stop_price,
                    account_equity=account_equity,
                )
                if not sizing.get("is_valid", False):
                    logger.info("Signal rejected by position sizer: {}", sizing.get("reason"))
                    return

                # Margin cap: notional value must not exceed 50% of equity per position
                # This prevents tiny risk-per-share from creating oversized notional positions
                max_notional = account_equity * 0.5  # 50% of equity per trade
                notional = sizing["shares"] * entry_price
                if notional > max_notional and sizing["shares"] > 1:
                    capped_shares = max(1, int(max_notional / entry_price))
                    logger.info(
                        "Margin cap {}: {} → {} shares (notional {:.0f} > {:.0f} max)",
                        self.symbol, sizing["shares"], capped_shares, notional, max_notional,
                    )
                    sizing["shares"] = capped_shares
                    sizing["risk_amount"] = round(capped_shares * abs(entry_price - stop_price), 2)

                # Apply drawdown scaling — reduce position as portfolio heat increases
                scale = self._circuit_breaker.get_position_scale()
                if scale < 1.0 and sizing.get("shares", 0) > 0:
                    original = sizing["shares"]
                    sizing["shares"] = max(1, int(sizing["shares"] * scale))
                    if sizing["shares"] != original:
                        logger.info(
                            "Drawdown scaling {}: {} → {} shares (scale={:.0%})",
                            self.symbol, original, sizing["shares"], scale,
                        )

                # Apply equity curve scaling — reduce size during losing streaks
                try:
                    async with async_session() as eq_session:
                        eq_scale = await db.get_equity_curve_scale(
                            eq_session, user_id=self.user_id,
                        )
                    if eq_scale < 1.0 and sizing.get("shares", 0) > 0:
                        original = sizing["shares"]
                        sizing["shares"] = max(1, int(sizing["shares"] * eq_scale))
                        if sizing["shares"] != original:
                            logger.info(
                                "Equity curve scaling {}: {} → {} shares (scale={:.0%})",
                                self.symbol, original, sizing["shares"], eq_scale,
                            )
                except Exception:
                    pass  # If equity curve check fails, proceed with current size

                # Apply correlation adjustment — reduce if correlated positions exist
                try:
                    async with async_session() as corr_session:
                        corr_scale = await db.check_correlated_positions(
                            corr_session, self.symbol, self.exchange, user_id=self.user_id,
                        )
                    if corr_scale < 1.0 and sizing.get("shares", 0) > 0:
                        original = sizing["shares"]
                        sizing["shares"] = max(1, int(sizing["shares"] * corr_scale))
                        if sizing["shares"] != original:
                            logger.info(
                                "Correlation scaling {}: {} → {} shares (scale={:.0%})",
                                self.symbol, original, sizing["shares"], corr_scale,
                            )
                except Exception:
                    pass

                # Check if this trade would breach 6% rule
                trade_risk = sizing.get("risk_amount", 0)
                if trade_risk > 0:
                    new_trade_check = cb.check_new_trade_risk(trade_risk)
                    if not new_trade_check.get("is_allowed", True):
                        logger.info(
                            "Signal rejected by 6% rule: {} (exposure {:.1f}%)",
                            self.symbol, new_trade_check.get("projected_pct", 0),
                        )
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
                    "user_id": self.user_id,
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

        # Execute
        if sizing.get("shares", 0) > 0:
            await self._auto_execute(signal, sizing, analysis)
        else:
            logger.info("Signal {} skipped: zero shares from position sizer", signal.id)

    def _validate_order(self, direction: str, quantity: int, price: float, stop: float) -> tuple:
        """Pre-trade validation — independent sanity checks before order placement.

        Returns (is_valid, reason).
        Catches: absurd prices, oversized positions, zero/negative values.
        Inspired by the Knight Capital incident — no order should reach the broker
        without an independent sanity check.
        """
        # 1. Price must be positive and reasonable
        if price <= 0:
            return False, f"Invalid price: {price}"

        # 2. Quantity must be positive
        if quantity <= 0:
            return False, f"Invalid quantity: {quantity}"

        # 3. Stop must be positive and on correct side
        if stop <= 0:
            return False, f"Invalid stop: {stop}"
        if direction == "BUY" and stop >= price:
            return False, f"BUY stop {stop} >= entry {price}"
        if direction == "SELL" and stop <= price:
            return False, f"SELL stop {stop} <= entry {price}"

        # 4. Risk per share must be reasonable (< 10% of price)
        risk_pct = abs(price - stop) / price * 100
        if risk_pct > 10:
            return False, f"Risk per share {risk_pct:.1f}% exceeds 10% limit"

        # 5. Max position value check (hard cap — 10x account equity or 1 crore)
        position_value = quantity * price
        max_value = 10_000_000  # 1 crore hard cap
        if position_value > max_value:
            return False, f"Position value {position_value:,.0f} exceeds {max_value:,.0f} hard cap"

        # 6. Max quantity check (hard cap at 50,000 units for futures)
        if quantity > 50_000:
            return False, f"Quantity {quantity} exceeds 50,000 hard cap"

        return True, "OK"

    async def _auto_execute(self, signal, sizing: dict, analysis: dict):
        """Auto-execute trade via TradeExecutor (PAPER and LIVE modes)."""
        rec = analysis["recommendation"]
        direction = "BUY" if rec["action"] == "BUY" else "SELL"
        pos_direction = "LONG" if direction == "BUY" else "SHORT"
        entry = rec.get("entry_price", 0)
        stop = rec.get("stop_price", 0)
        shares = sizing.get("shares", 0)

        if shares <= 0 or entry <= 0:
            return

        # Pre-trade validation — independent sanity check (Knight Capital lesson)
        is_valid, reason = self._validate_order(direction, shares, entry, stop)
        if not is_valid:
            logger.warning(
                "Order REJECTED by pre-trade validation for {}: {}",
                self.symbol, reason,
            )
            await self._broadcast_event("order_rejected", {
                "symbol": self.symbol, "direction": direction,
                "quantity": shares, "reason": f"Pre-trade validation: {reason}",
            })
            try:
                from app.notifications.telegram import notify_order_rejected
                await notify_order_rejected(
                    symbol=self.symbol, direction=direction,
                    quantity=shares, reason=f"Pre-trade validation: {reason}",
                    mode=self.effective_trading_mode,
                )
            except Exception:
                pass
            return

        # SEBI circular: Market orders prohibited for algorithmic trading from April 1, 2026.
        # Use LIMIT orders with a small buffer to ensure fills while remaining compliant.
        # BUY: limit price 0.2% above entry; SELL: limit price 0.2% below entry.
        if direction == "BUY":
            limit_price = round(entry * 1.002, 2)
        else:
            limit_price = round(entry * 0.998, 2)

        # Calculate target price (2:1 R:R by default)
        risk_per_share = abs(entry - stop) if stop > 0 else 0
        rr_multiplier = getattr(settings, "rr_target_multiplier", 2.0)
        if direction == "BUY":
            target = entry + (risk_per_share * rr_multiplier) if risk_per_share > 0 else 0
        else:
            target = entry - (risk_per_share * rr_multiplier) if risk_per_share > 0 else 0

        mode = self.effective_trading_mode  # Per-asset or global

        try:
            # Check if we need to flip an existing position
            existing = self.executor.get_position(self.symbol)
            if existing and existing.is_open and existing.direction != pos_direction:
                # Flip: exit current + enter opposite
                logger.info("Flipping {} -> {} for {}", existing.direction, pos_direction, self.symbol)
                current_price = entry
                # Close existing position in DB
                async with async_session() as session:
                    positions = await db.load_open_positions_by_symbol(session, self.symbol)
                    for pos in positions:
                        if pos.direction == existing.direction:
                            await db.close_position(session, pos.id, current_price)
                # Exit via executor
                await self.executor.exit_position(
                    self.symbol, ExitReason.FLIP, current_price=current_price,
                    token=self.token, exchange=self.exchange,
                )

            # Enter via executor (uses PaperPlacer or LivePlacer internally)
            # Retry up to 2 times for LIVE mode rejections (e.g., transient broker errors)
            max_retries = 2 if mode == "LIVE" else 0
            exec_pos = None
            for attempt in range(max_retries + 1):
                exec_pos = await self.executor.enter(
                    symbol=self.symbol, token=self.token, exchange=self.exchange,
                    direction=pos_direction, quantity=shares,
                    entry_price=limit_price, stop_price=stop, target_price=round(target, 2),
                    order_type="LIMIT", product_type="CARRYFORWARD",
                )
                if exec_pos is not None:
                    break
                if attempt < max_retries:
                    logger.warning(
                        "Entry attempt {}/{} failed for {}, retrying in {}s...",
                        attempt + 1, max_retries + 1, self.symbol, (attempt + 1),
                    )
                    await asyncio.sleep(attempt + 1)  # 1s, 2s backoff

            if exec_pos is None:
                logger.error("Executor entry failed after {} attempts for {}", max_retries + 1, self.symbol)
                await self._broadcast_event("order_rejected", {
                    "symbol": self.symbol, "direction": direction,
                    "quantity": shares, "reason": "All retry attempts exhausted",
                })
                try:
                    from app.notifications.telegram import notify_order_rejected
                    await notify_order_rejected(
                        symbol=self.symbol, direction=direction,
                        quantity=shares, reason="All retry attempts exhausted",
                        mode=mode,
                    )
                except Exception:
                    pass
                return

            broker_order_id = exec_pos.entry_order_id or f"PIPE-{signal.id:04d}"
            filled_price = exec_pos.entry_price or entry
            order_status = "COMPLETE" if exec_pos.state.value == "OPEN" else "PENDING"

            # Persist to DB
            async with async_session() as session:
                order = await db.save_order(session, {
                    "user_id": self.user_id,
                    "signal_id": signal.id,
                    "instrument_id": self.instrument_id,
                    "symbol": self.symbol,
                    "order_id": broker_order_id,
                    "direction": direction,
                    "order_type": "LIMIT",
                    "quantity": shares,
                    "price": limit_price,
                    "status": order_status,
                    "mode": mode,
                    "filled_price": filled_price if order_status == "COMPLETE" else None,
                    "filled_quantity": shares if order_status == "COMPLETE" else None,
                })

                position = await db.save_position(session, {
                    "user_id": self.user_id,
                    "instrument_id": self.instrument_id,
                    "symbol": self.symbol,
                    "direction": pos_direction,
                    "entry_price": filled_price,
                    "quantity": shares,
                    "stop_price": stop,
                    "target_price": round(target, 2),
                    "current_price": filled_price,
                    "risk_amount": sizing.get("risk_amount", 0),
                    "risk_percent": sizing.get("actual_risk_pct", 0),
                    "mode": mode,
                })

            # Clear exit dedup set — new position opened
            self._exit_initiated.clear()

            logger.info(
                "[{}] Auto-executed: {} {} x{} @ {:.2f} stop={:.2f} target={:.2f} order={}",
                mode, direction, self.symbol, shares, filled_price, stop, target, broker_order_id,
            )

            # Telegram trade notification
            try:
                from app.notifications.telegram import notify_trade
                await notify_trade(
                    self.symbol, direction, shares, filled_price, stop,
                    broker_order_id, mode, analysis.get("grade", "?"),
                )
            except Exception:
                pass

            await self._broadcast_event("order", {
                "symbol": self.symbol,
                "direction": direction,
                "quantity": shares,
                "price": filled_price,
                "stop_price": stop,
                "target_price": round(target, 2),
                "order_id": broker_order_id,
                "mode": mode,
                "status": order_status,
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
            "contract": self.contract_symbol,
            "expiry_date": self.expiry_date.strftime("%Y-%m-%d") if self.expiry_date else None,
            "days_to_expiry": (self.expiry_date - datetime.now()).days if self.expiry_date else None,
            "trading_mode": self.effective_trading_mode,
            "adx": last_non_null(self.indicators.get(
                self.screen_timeframes.get("1", "1w"), {}
            ).get("adx", [])),
        }

    def stop(self):
        """Stop tracking this asset."""
        self.active = False
        self.candle_builders.clear()
        logger.info("AssetSession stopped: {}:{}", self.symbol, self.exchange)
