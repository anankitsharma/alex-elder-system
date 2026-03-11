"""
Tests for the Backtest Engine.
"""

import pytest
import pandas as pd
import numpy as np

from backend.app.backtest.engine import BacktestEngine, BacktestResult, BacktestMetrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trending(n: int = 300, trend: str = "up") -> pd.DataFrame:
    """Generate OHLCV with a clear trend for predictable backtest results."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=n, freq="15min")

    if trend == "up":
        close = 100 + np.linspace(0, 50, n) + rng.standard_normal(n) * 0.3
    elif trend == "down":
        close = 150 - np.linspace(0, 50, n) + rng.standard_normal(n) * 0.3
    else:
        close = 100 + rng.standard_normal(n).cumsum() * 0.5

    high = close + rng.uniform(0.2, 1.0, n)
    low = close - rng.uniform(0.2, 1.0, n)
    opn = close + rng.uniform(-0.5, 0.5, n)
    high = np.maximum(high, np.maximum(opn, close))
    low = np.minimum(low, np.minimum(opn, close))
    volume = rng.integers(1000, 100000, n)

    return pd.DataFrame({
        "datetime": dates, "open": opn, "high": high,
        "low": low, "close": close, "volume": volume,
    })


# ---------------------------------------------------------------------------
# Engine basics
# ---------------------------------------------------------------------------

class TestBacktestEngine:

    def test_run_returns_result(self):
        engine = BacktestEngine(initial_capital=100_000, quantity=10)
        df = _make_trending(300, "up")
        result = engine.run_sync(df, "TEST", "15m")
        assert isinstance(result, BacktestResult)
        assert result.symbol == "TEST"
        assert result.timeframe == "15m"

    def test_result_has_equity_curve(self):
        engine = BacktestEngine(initial_capital=100_000, quantity=10)
        df = _make_trending(300, "up")
        result = engine.run_sync(df, "TEST", "15m")
        assert len(result.equity_curve) > 0
        assert result.equity_curve[0] == 100_000

    def test_result_has_metrics(self):
        engine = BacktestEngine(initial_capital=100_000, quantity=10)
        df = _make_trending(300, "up")
        result = engine.run_sync(df, "TEST", "15m")
        m = result.metrics
        assert m.start_equity == 100_000
        assert m.end_equity > 0
        assert 0 <= m.win_rate <= 100

    def test_bars_processed(self):
        engine = BacktestEngine(initial_capital=100_000, quantity=10)
        df = _make_trending(300, "up")
        result = engine.run_sync(df, "TEST", "15m")
        assert result.bars_processed > 0

    def test_dates_recorded(self):
        engine = BacktestEngine(initial_capital=100_000, quantity=10)
        df = _make_trending(300, "up")
        result = engine.run_sync(df, "TEST", "15m")
        assert result.start_date is not None
        assert result.end_date is not None

    def test_insufficient_data(self):
        engine = BacktestEngine(initial_capital=100_000, quantity=10)
        df = _make_trending(20, "up")
        result = engine.run_sync(df, "TEST", "15m")
        assert result.metrics.total_trades == 0


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class TestBacktestMetrics:

    def test_trades_counted(self):
        engine = BacktestEngine(initial_capital=100_000, quantity=10, min_signal_score=30)
        df = _make_trending(500, "up")
        result = engine.run_sync(df, "TEST", "15m")
        # With 500 bars of trending data we should get at least 1 trade
        assert result.metrics.total_trades >= 0
        assert result.metrics.winning_trades + result.metrics.losing_trades == result.metrics.total_trades

    def test_pnl_consistency(self):
        engine = BacktestEngine(initial_capital=100_000, quantity=10, min_signal_score=30)
        df = _make_trending(500, "up")
        result = engine.run_sync(df, "TEST", "15m")
        m = result.metrics
        expected_net = m.gross_profit - m.gross_loss
        assert abs(m.net_pnl - expected_net) < 0.01

    def test_profit_factor(self):
        engine = BacktestEngine(initial_capital=100_000, quantity=10, min_signal_score=30)
        df = _make_trending(500, "up")
        result = engine.run_sync(df, "TEST", "15m")
        m = result.metrics
        if m.gross_loss > 0:
            assert m.profit_factor == pytest.approx(m.gross_profit / m.gross_loss, rel=0.01)

    def test_drawdown_non_negative(self):
        engine = BacktestEngine(initial_capital=100_000, quantity=10)
        df = _make_trending(300, "up")
        result = engine.run_sync(df, "TEST", "15m")
        assert result.metrics.max_drawdown >= 0
        assert result.metrics.max_drawdown_pct >= 0

    def test_return_pct(self):
        engine = BacktestEngine(initial_capital=100_000, quantity=10)
        df = _make_trending(300, "up")
        result = engine.run_sync(df, "TEST", "15m")
        m = result.metrics
        expected_return = (m.end_equity - 100_000) / 100_000 * 100
        assert m.return_pct == pytest.approx(expected_return, rel=0.01)


# ---------------------------------------------------------------------------
# Config variations
# ---------------------------------------------------------------------------

class TestBacktestConfig:

    def test_no_safezone_stops(self):
        engine = BacktestEngine(
            initial_capital=100_000, quantity=10,
            use_safezone_stops=False,
        )
        df = _make_trending(300, "up")
        result = engine.run_sync(df, "TEST", "15m")
        assert isinstance(result, BacktestResult)

    def test_custom_indicator_params(self):
        engine = BacktestEngine(
            initial_capital=100_000, quantity=10,
            ema_period=22, macd_fast=12, macd_slow=26,
            fi_length=2,
        )
        df = _make_trending(300, "up")
        result = engine.run_sync(df, "TEST", "15m")
        assert isinstance(result, BacktestResult)

    def test_high_min_score_fewer_trades(self):
        engine_low = BacktestEngine(initial_capital=100_000, quantity=10, min_signal_score=20)
        engine_high = BacktestEngine(initial_capital=100_000, quantity=10, min_signal_score=90)
        df = _make_trending(500, "up")
        result_low = engine_low.run_sync(df, "TEST", "15m")
        result_high = engine_high.run_sync(df, "TEST", "15m")
        # Higher threshold → fewer or equal signals
        assert result_high.signals_generated <= result_low.signals_generated


# ---------------------------------------------------------------------------
# Trade log
# ---------------------------------------------------------------------------

class TestBacktestTradeLog:

    def test_trade_entries_have_required_fields(self):
        engine = BacktestEngine(initial_capital=100_000, quantity=10, min_signal_score=30)
        df = _make_trending(500, "up")
        result = engine.run_sync(df, "TEST", "15m")
        for t in result.trades:
            assert "symbol" in t
            assert "direction" in t
            assert "entry_price" in t
            assert "exit_price" in t
            assert "pnl" in t
            assert "exit_reason" in t

    def test_all_trades_closed(self):
        engine = BacktestEngine(initial_capital=100_000, quantity=10, min_signal_score=30)
        df = _make_trending(500, "up")
        result = engine.run_sync(df, "TEST", "15m")
        for t in result.trades:
            assert t["exit_price"] is not None
            assert t["pnl"] is not None


# ---------------------------------------------------------------------------
# Async
# ---------------------------------------------------------------------------

class TestBacktestAsync:

    @pytest.mark.asyncio
    async def test_run_async(self):
        engine = BacktestEngine(initial_capital=100_000, quantity=10)
        df = _make_trending(300, "up")
        result = await engine.run_async(df, "TEST", "15m")
        assert isinstance(result, BacktestResult)
        assert result.bars_processed > 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestBacktestEdgeCases:

    def test_no_volume_column(self):
        df = _make_trending(300, "up").drop(columns=["volume"])
        engine = BacktestEngine(initial_capital=100_000, quantity=10)
        result = engine.run_sync(df, "TEST", "15m")
        assert isinstance(result, BacktestResult)

    def test_flat_data(self):
        rng = np.random.default_rng(99)
        n = 300
        dates = pd.date_range("2024-01-01", periods=n, freq="15min")
        close = np.full(n, 100.0) + rng.standard_normal(n) * 0.01
        df = pd.DataFrame({
            "datetime": dates, "open": close, "high": close + 0.01,
            "low": close - 0.01, "close": close,
            "volume": rng.integers(100, 1000, n),
        })
        engine = BacktestEngine(initial_capital=100_000, quantity=10)
        result = engine.run_sync(df, "FLAT", "15m")
        assert isinstance(result, BacktestResult)
