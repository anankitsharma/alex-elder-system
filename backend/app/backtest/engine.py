"""
Backtest Engine

Replays historical OHLCV data bar-by-bar through the Elder indicator stack,
generates signals, executes trades via PaperPlacer, and collects performance metrics.
"""

from __future__ import annotations

import asyncio
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from loguru import logger

from backend.app.indicators.ema import EMAEnhanced
from backend.app.indicators.macd import MACDEnhanced
from backend.app.indicators.force_index import ForceIndexEnhanced
from backend.app.indicators.impulse import ElderImpulseEnhanced
from backend.app.indicators.safezone import SafeZoneV2
from backend.app.trading.executor import TradeExecutor, TradePosition, ExitReason
from backend.app.trading.paper import PaperPlacer


# ---------------------------------------------------------------------------
# Performance metrics
# ---------------------------------------------------------------------------

@dataclass
class BacktestMetrics:
    """Aggregate performance statistics for a backtest run."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_pnl: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    avg_trade_duration_bars: float = 0.0
    start_equity: float = 0.0
    end_equity: float = 0.0
    return_pct: float = 0.0


@dataclass
class BacktestResult:
    """Full backtest output including trades and equity curve."""
    symbol: str
    timeframe: str
    metrics: BacktestMetrics
    trades: List[Dict[str, Any]] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    signals_generated: int = 0
    bars_processed: int = 0
    start_date: Optional[str] = None
    end_date: Optional[str] = None


# ---------------------------------------------------------------------------
# Backtest Engine
# ---------------------------------------------------------------------------

class BacktestEngine:
    """
    Bar-by-bar historical backtest using Elder Three-Screen indicators.

    Usage:
        engine = BacktestEngine(initial_capital=100_000)
        result = engine.run(df, "NIFTY", "15m")
        print(result.metrics)
    """

    def __init__(
        self,
        initial_capital: float = 100_000,
        quantity: int = 75,
        slippage_pct: float = 0.001,
        # Indicator params
        ema_period: int = 13,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        fi_length: int = 13,
        sz_lookback: int = 22,
        sz_coefficient: float = 2.0,
        # Signal thresholds
        min_signal_score: float = 40,
        use_safezone_stops: bool = True,
    ):
        self.initial_capital = initial_capital
        self.quantity = quantity
        self.slippage_pct = slippage_pct

        self.ema_period = ema_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.fi_length = fi_length
        self.sz_lookback = sz_lookback
        self.sz_coefficient = sz_coefficient

        self.min_signal_score = min_signal_score
        self.use_safezone_stops = use_safezone_stops

        logger.info(f"BacktestEngine initialized — capital={initial_capital}, qty={quantity}")

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, df: pd.DataFrame, symbol: str, timeframe: str) -> BacktestResult:
        """
        Run backtest on historical data.

        Args:
            df: OHLCV DataFrame with columns: datetime, open, high, low, close, volume
            symbol: Symbol name
            timeframe: e.g. "15m", "1h"

        Returns:
            BacktestResult with metrics, trades, and equity curve.
        """
        return asyncio.get_event_loop().run_until_complete(
            self._run_async(df, symbol, timeframe)
        ) if not self._in_async_context() else self._run_sync_wrapper(df, symbol, timeframe)

    def run_sync(self, df: pd.DataFrame, symbol: str, timeframe: str) -> BacktestResult:
        """Synchronous backtest — uses a fresh event loop."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._run_async(df, symbol, timeframe))
        finally:
            loop.close()

    async def run_async(self, df: pd.DataFrame, symbol: str, timeframe: str) -> BacktestResult:
        """Async backtest entry point."""
        return await self._run_async(df, symbol, timeframe)

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    async def _run_async(self, df: pd.DataFrame, symbol: str, timeframe: str) -> BacktestResult:
        df = df.copy().reset_index(drop=True)

        if len(df) < self.sz_lookback + 15:
            logger.warning(f"Insufficient data for backtest: {len(df)} bars")
            return BacktestResult(symbol, timeframe, BacktestMetrics())

        # Pre-calculate indicators on full data
        indicators = self._calculate_indicators(df, symbol, timeframe)
        if indicators is None:
            return BacktestResult(symbol, timeframe, BacktestMetrics())

        # Set up executor
        placer = PaperPlacer(slippage_pct=self.slippage_pct)
        executor = TradeExecutor(placer)

        equity = self.initial_capital
        equity_curve = [equity]
        trade_log: List[Dict[str, Any]] = []
        signals_count = 0
        warmup = max(self.macd_slow + self.macd_signal, self.sz_lookback) + 5

        # Bar-by-bar replay
        for i in range(warmup, len(df)):
            bar = df.iloc[i]
            current_price = float(bar["close"])
            high = float(bar["high"])
            low = float(bar["low"])

            # Check stoploss on existing position
            pos = executor.get_position(symbol)
            if pos and pos.is_open and pos.stop_price is not None:
                # Check if stop was hit during this bar
                stop_hit = False
                if pos.direction == "LONG" and low <= pos.stop_price:
                    stop_hit = True
                    exit_price = pos.stop_price
                elif pos.direction == "SHORT" and high >= pos.stop_price:
                    stop_hit = True
                    exit_price = pos.stop_price

                if stop_hit:
                    closed = await executor.exit_position(
                        symbol, ExitReason.STOPLOSS, current_price=exit_price,
                    )
                    if closed and closed.is_closed:
                        trade_log.append(self._format_trade(closed, i))
                        equity += closed.pnl or 0

            # Get indicator values at this bar
            impulse_signal = indicators["impulse_signals"][i]
            impulse_color = indicators["impulse_colors"][i]
            fi_value = indicators["fi_values"][i]
            sz_long = indicators["sz_long"][i]
            sz_short = indicators["sz_short"][i]

            # NaN guard (numpy NaN from indicator output)
            if sz_long is not None and (isinstance(sz_long, float) and np.isnan(sz_long)):
                sz_long = None
            if sz_short is not None and (isinstance(sz_short, float) and np.isnan(sz_short)):
                sz_short = None
            if fi_value is not None and (isinstance(fi_value, float) and np.isnan(fi_value)):
                fi_value = None

            # Signal logic
            pos = executor.get_position(symbol)
            signal = self._evaluate_signal(
                impulse_signal, impulse_color, fi_value, current_price
            )

            if signal and signal["score"] >= self.min_signal_score:
                signals_count += 1

                if pos is None or not pos.is_open:
                    # Enter new position
                    stop = None
                    if self.use_safezone_stops:
                        if signal["direction"] == "LONG" and sz_long is not None:
                            stop = sz_long
                        elif signal["direction"] == "SHORT" and sz_short is not None:
                            stop = sz_short

                    await executor.enter(
                        symbol=symbol, token="BT", exchange="BT",
                        direction=signal["direction"],
                        quantity=self.quantity,
                        entry_price=current_price,
                        stop_price=stop,
                    )

                elif pos.is_open and signal["direction"] != pos.direction:
                    # Flip: opposite signal
                    stop = None
                    if self.use_safezone_stops:
                        if signal["direction"] == "LONG" and sz_long is not None:
                            stop = sz_long
                        elif signal["direction"] == "SHORT" and sz_short is not None:
                            stop = sz_short

                    closed = await executor.exit_position(
                        symbol, ExitReason.SIGNAL, current_price=current_price,
                    )
                    if closed and closed.is_closed:
                        trade_log.append(self._format_trade(closed, i))
                        equity += closed.pnl or 0

                    await executor.enter(
                        symbol=symbol, token="BT", exchange="BT",
                        direction=signal["direction"],
                        quantity=self.quantity,
                        entry_price=current_price,
                        stop_price=stop,
                    )

            # Trail stop if we have SafeZone values
            pos = executor.get_position(symbol)
            if pos and pos.is_open and self.use_safezone_stops:
                if pos.direction == "LONG" and sz_long is not None:
                    executor.update_stop(symbol, sz_long)
                elif pos.direction == "SHORT" and sz_short is not None:
                    executor.update_stop(symbol, sz_short)

            equity_curve.append(equity)

        # Close any remaining position at last price
        pos = executor.get_position(symbol)
        if pos and pos.is_open:
            final_price = float(df["close"].iloc[-1])
            closed = await executor.exit_position(
                symbol, ExitReason.EOD, current_price=final_price,
            )
            if closed and closed.is_closed:
                trade_log.append(self._format_trade(closed, len(df) - 1))
                equity += closed.pnl or 0
                equity_curve[-1] = equity

        # Compute metrics
        metrics = self._compute_metrics(trade_log, equity_curve)

        start_date = str(df["datetime"].iloc[0]) if "datetime" in df.columns else None
        end_date = str(df["datetime"].iloc[-1]) if "datetime" in df.columns else None

        return BacktestResult(
            symbol=symbol,
            timeframe=timeframe,
            metrics=metrics,
            trades=trade_log,
            equity_curve=equity_curve,
            signals_generated=signals_count,
            bars_processed=len(df) - warmup,
            start_date=start_date,
            end_date=end_date,
        )

    # ------------------------------------------------------------------
    # Indicator pre-calculation
    # ------------------------------------------------------------------

    def _calculate_indicators(
        self, df: pd.DataFrame, symbol: str, timeframe: str
    ) -> Optional[Dict[str, Any]]:
        """Pre-calculate all indicators on the full dataset."""
        n = len(df)

        def _pad(values: list, length: int, fill=None) -> list:
            """Left-pad a shorter list to match the original DataFrame length."""
            if len(values) >= length:
                return values[:length]
            return [fill] * (length - len(values)) + values

        try:
            # Impulse (includes EMA + MACD internally)
            impulse = ElderImpulseEnhanced(symbol, timeframe, {
                "ema_length": self.ema_period,
                "macd_fast_length": self.macd_fast,
                "macd_slow_length": self.macd_slow,
                "macd_signal_length": self.macd_signal,
            })
            impulse_df = impulse.calculate(df)

            raw_signals = impulse_df["impulse_signal"].tolist() if "impulse_signal" in impulse_df.columns else []
            raw_colors = impulse_df["impulse_color"].tolist() if "impulse_color" in impulse_df.columns else []

            result: Dict[str, Any] = {
                "impulse_signals": _pad(raw_signals, n, "neutral"),
                "impulse_colors": _pad(raw_colors, n, "blue"),
            }

            # Force Index
            has_volume = "volume" in df.columns and df["volume"].sum() > 0
            if has_volume:
                try:
                    fi = ForceIndexEnhanced(symbol, timeframe, {"length": self.fi_length})
                    fi_df = fi.calculate(df)
                    raw_fi = fi_df["value"].tolist() if "value" in fi_df.columns else []
                    result["fi_values"] = _pad(raw_fi, n, None)
                except Exception:
                    result["fi_values"] = [None] * n
            else:
                result["fi_values"] = [None] * n

            # SafeZone
            if self.use_safezone_stops and n >= self.sz_lookback + 10:
                try:
                    sz = SafeZoneV2(symbol, timeframe, {
                        "lookback_length": self.sz_lookback,
                        "coefficient": self.sz_coefficient,
                    })
                    sz_df = sz.calculate(df)
                    raw_long = sz_df["longvs"].tolist() if "longvs" in sz_df.columns else []
                    raw_short = sz_df["shortvs"].tolist() if "shortvs" in sz_df.columns else []
                    result["sz_long"] = _pad(raw_long, n, None)
                    result["sz_short"] = _pad(raw_short, n, None)
                except Exception:
                    result["sz_long"] = [None] * n
                    result["sz_short"] = [None] * n
            else:
                result["sz_long"] = [None] * n
                result["sz_short"] = [None] * n

            return result

        except Exception as e:
            logger.error(f"Failed to calculate indicators: {e}")
            return None

    # ------------------------------------------------------------------
    # Signal evaluation
    # ------------------------------------------------------------------

    def _evaluate_signal(
        self,
        impulse_signal: str,
        impulse_color: str,
        fi_value: Optional[float],
        current_price: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Decide whether to generate a trade signal at this bar.

        Rules:
          - Green impulse → LONG candidate
          - Red impulse → SHORT candidate
          - Force Index alignment boosts score
        """
        if impulse_signal == "neutral" or impulse_signal is None:
            return None

        score = 0.0
        direction = "LONG" if impulse_signal == "bullish" else "SHORT"

        # Base impulse score
        score += 40

        # Force Index confirmation
        if fi_value is not None:
            if direction == "LONG" and fi_value > 0:
                score += 30
            elif direction == "SHORT" and fi_value < 0:
                score += 30
            elif direction == "LONG" and fi_value < 0:
                score -= 10
            elif direction == "SHORT" and fi_value > 0:
                score -= 10

        # Impulse color strength
        if impulse_color in ("green", "red"):
            score += 20

        score = max(0, min(100, score))

        return {"direction": direction, "score": score}

    # ------------------------------------------------------------------
    # Metrics computation
    # ------------------------------------------------------------------

    def _compute_metrics(
        self,
        trades: List[Dict[str, Any]],
        equity_curve: List[float],
    ) -> BacktestMetrics:
        m = BacktestMetrics()
        m.start_equity = self.initial_capital

        if not trades:
            m.end_equity = equity_curve[-1] if equity_curve else self.initial_capital
            return m

        pnls = [t["pnl"] for t in trades if t["pnl"] is not None]
        m.total_trades = len(pnls)

        if m.total_trades == 0:
            m.end_equity = equity_curve[-1] if equity_curve else self.initial_capital
            return m

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        m.winning_trades = len(wins)
        m.losing_trades = len(losses)
        m.gross_profit = sum(wins)
        m.gross_loss = abs(sum(losses))
        m.net_pnl = sum(pnls)
        m.win_rate = (m.winning_trades / m.total_trades * 100) if m.total_trades > 0 else 0.0
        m.profit_factor = (m.gross_profit / m.gross_loss) if m.gross_loss > 0 else float("inf") if m.gross_profit > 0 else 0.0
        m.avg_win = (m.gross_profit / m.winning_trades) if m.winning_trades > 0 else 0.0
        m.avg_loss = (m.gross_loss / m.losing_trades) if m.losing_trades > 0 else 0.0
        m.end_equity = equity_curve[-1] if equity_curve else self.initial_capital
        m.return_pct = ((m.end_equity - m.start_equity) / m.start_equity * 100) if m.start_equity > 0 else 0.0

        # Max drawdown
        peak = equity_curve[0]
        max_dd = 0.0
        max_dd_pct = 0.0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = peak - eq
            dd_pct = (dd / peak * 100) if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
                max_dd_pct = dd_pct
        m.max_drawdown = max_dd
        m.max_drawdown_pct = max_dd_pct

        # Sharpe ratio (using trade returns, annualised by sqrt(252))
        if len(pnls) > 1:
            returns = np.array(pnls) / self.initial_capital
            mean_ret = np.mean(returns)
            std_ret = np.std(returns, ddof=1)
            m.sharpe_ratio = float((mean_ret / std_ret) * np.sqrt(252)) if std_ret > 0 else 0.0
        else:
            m.sharpe_ratio = 0.0

        # Consecutive wins/losses
        m.max_consecutive_wins = self._max_consecutive(pnls, positive=True)
        m.max_consecutive_losses = self._max_consecutive(pnls, positive=False)

        # Average trade duration (in bars)
        durations = [t.get("duration_bars", 0) for t in trades]
        m.avg_trade_duration_bars = float(np.mean(durations)) if durations else 0.0

        return m

    @staticmethod
    def _max_consecutive(pnls: List[float], positive: bool) -> int:
        max_streak = 0
        current = 0
        for p in pnls:
            if (positive and p > 0) or (not positive and p <= 0):
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_trade(pos: TradePosition, bar_index: int) -> Dict[str, Any]:
        entry_bar = getattr(pos, "_entry_bar", 0)
        return {
            "symbol": pos.symbol,
            "direction": pos.direction,
            "entry_price": pos.entry_price,
            "exit_price": pos.exit_price,
            "quantity": pos.quantity,
            "pnl": pos.pnl,
            "exit_reason": pos.exit_reason.value if pos.exit_reason else None,
            "entry_time": str(pos.entry_time) if pos.entry_time else None,
            "exit_time": str(pos.exit_time) if pos.exit_time else None,
            "duration_bars": bar_index - entry_bar,
        }

    @staticmethod
    def _in_async_context() -> bool:
        try:
            asyncio.get_running_loop()
            return True
        except RuntimeError:
            return False

    def _run_sync_wrapper(self, df, symbol, timeframe):
        """Fallback when already in an async context — create nested loop."""
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(self.run_sync, df, symbol, timeframe)
            return future.result()
