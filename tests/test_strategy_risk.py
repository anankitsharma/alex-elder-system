"""
Tests for Signal Manager and SafeZone Stoploss system.
"""

import pytest
import pandas as pd
import numpy as np
from types import SimpleNamespace
from backend.app.strategy.signals import SignalManager, DEFAULT_TIMEFRAME_HIERARCHY
from backend.app.risk.stops import SafeZoneStoploss


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 100, seed: int = 42) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    close = 100 + np.cumsum(rng.randn(n) * 0.5)
    high = close + rng.uniform(0.2, 1.0, n)
    low = close - rng.uniform(0.2, 1.0, n)
    opn = close + rng.uniform(-0.5, 0.5, n)
    high = np.maximum(high, np.maximum(opn, close))
    low = np.minimum(low, np.minimum(opn, close))
    volume = rng.randint(1000, 50000, n).astype(float)
    dt = pd.date_range("2025-01-01", periods=n, freq="15min")
    return pd.DataFrame({
        "datetime": dt, "open": opn, "high": high,
        "low": low, "close": close, "volume": volume,
    })


def _make_indicators(impulse="bullish", fi_13=0.5, fi_2=0.3):
    """Create a mock indicator bundle."""
    return SimpleNamespace(
        impulse_signal=impulse,
        impulse_color="GREEN" if impulse == "bullish" else "RED" if impulse == "bearish" else "BLUE",
        fi_13=fi_13,
        fi_2=fi_2,
        fi_value=fi_13,
        ema_value=100.0,
        safezone_long=98.0,
        safezone_short=102.0,
    )


@pytest.fixture
def ohlcv():
    return _make_ohlcv(100)


# ===========================================================================
# SignalManager Tests
# ===========================================================================

class TestSignalManager:

    def test_init_default_timeframes(self):
        sm = SignalManager()
        assert sm.timeframes == DEFAULT_TIMEFRAME_HIERARCHY

    def test_init_custom_timeframes(self):
        tfs = ["4h", "1h", "15m"]
        sm = SignalManager(timeframes=tfs)
        assert sm.timeframes == tfs

    def test_no_signal_when_no_current(self):
        sm = SignalManager(timeframes=["1h", "15m"])
        indicators = SimpleNamespace()  # no impulse_signal
        result = sm.generate_signals("TEST", "15m", indicators, {})
        assert result is None

    def test_no_signal_when_hold(self):
        sm = SignalManager(timeframes=["1h", "15m"])
        indicators = SimpleNamespace(impulse_signal="HOLD")
        result = sm.generate_signals("TEST", "15m", indicators, {})
        assert result is None

    def test_no_signal_without_confirmation(self):
        sm = SignalManager(timeframes=["1h", "15m"])
        indicators = _make_indicators("bullish")
        # Higher timeframe says bearish — no confirmation
        higher = _make_indicators("bearish")
        result = sm.generate_signals("TEST", "15m", indicators, {"1h": higher})
        assert result is None

    def test_signal_with_confirmation(self):
        sm = SignalManager(timeframes=["1h", "15m"])
        indicators = _make_indicators("bullish")
        higher = _make_indicators("bullish")
        result = sm.generate_signals("TEST", "15m", indicators, {"1h": higher})
        assert result is not None
        assert result["direction"] == "LONG"
        assert result["symbol"] == "TEST"
        assert result["timeframe"] == "15m"
        assert result["cross_timeframe_confirmation"] is True
        assert 0 <= result["score"] <= 100

    def test_bearish_signal(self):
        sm = SignalManager(timeframes=["1h", "15m"])
        indicators = _make_indicators("bearish")
        higher = _make_indicators("bearish")
        result = sm.generate_signals("TEST", "15m", indicators, {"1h": higher})
        assert result is not None
        assert result["direction"] == "SHORT"

    def test_strength_increases_with_confirmations(self):
        sm = SignalManager(timeframes=["4h", "1h", "15m"])
        indicators = _make_indicators("bullish")

        # One confirmation
        result1 = sm.generate_signals(
            "TEST", "15m", indicators, {"1h": _make_indicators("bullish")}
        )

        # Two confirmations
        result2 = sm.generate_signals(
            "TEST", "15m", indicators,
            {"4h": _make_indicators("bullish"), "1h": _make_indicators("bullish")},
        )

        assert result1 is not None and result2 is not None
        assert result2["score"] >= result1["score"]

    def test_timeframe_not_in_hierarchy(self):
        sm = SignalManager(timeframes=["1h", "15m"])
        indicators = _make_indicators("bullish")
        result = sm.generate_signals("TEST", "3m", indicators, {})
        assert result is None

    def test_extract_direction_variants(self):
        sm = SignalManager()
        assert sm._extract_direction(SimpleNamespace(impulse_signal="BUY")) == "LONG"
        assert sm._extract_direction(SimpleNamespace(impulse_signal="SELL")) == "SHORT"
        assert sm._extract_direction(SimpleNamespace(direction="LONG")) == "LONG"
        assert sm._extract_direction(SimpleNamespace(triple_screen_signal="BEARISH")) == "SHORT"
        assert sm._extract_direction(SimpleNamespace()) is None


# ===========================================================================
# SafeZoneStoploss Tests
# ===========================================================================

class TestSafeZoneStoploss:

    def _make(self, **overrides):
        config = {
            "safezone_lookback": 22,
            "safezone_coefficient": 2.0,
            "ema_period": 22,
            "rr_target_multiplier": 2.0,
            "min_distance_pct": 0.01,
        }
        config.update(overrides)
        return SafeZoneStoploss("TEST", "15m", config)

    def test_init(self):
        sl = self._make()
        assert sl.symbol == "TEST"
        assert sl.timeframe == "15m"
        assert sl.current_stoploss is None

    def test_initial_buy_stoploss(self, ohlcv):
        sl = self._make()
        result = sl.calculate_initial_stoploss(ohlcv, 100.0, "BUY")
        assert result["is_valid"] is True
        assert result["stoploss_price"] is not None
        assert result["stoploss_price"] < 100.0  # SL below entry for BUY
        assert result["stoploss_type"] == "INITIAL"
        assert result["risk_metrics"]["risk_amount"] > 0

    def test_initial_sell_stoploss(self, ohlcv):
        sl = self._make()
        result = sl.calculate_initial_stoploss(ohlcv, 100.0, "SELL")
        assert result["is_valid"] is True
        assert result["stoploss_price"] > 100.0  # SL above entry for SELL
        assert result["stoploss_type"] == "INITIAL"

    def test_empty_data_returns_invalid(self):
        sl = self._make()
        empty = pd.DataFrame()
        result = sl.calculate_initial_stoploss(empty, 100.0, "BUY")
        assert result["is_valid"] is False

    def test_trailing_up_for_buy(self, ohlcv):
        sl = self._make()
        sl.calculate_initial_stoploss(ohlcv, 90.0, "BUY")
        initial_sl = sl.current_stoploss["stoploss_price"]

        # "Price moved up" → update with higher current price
        result = sl.update_stoploss(ohlcv, 110.0, "BUY")
        assert result["stoploss_price"] >= initial_sl
        assert result["stoploss_type"] in ("TRAILING_UP", "MAINTAINED")

    def test_trailing_never_widens_buy(self, ohlcv):
        sl = self._make()
        sl.calculate_initial_stoploss(ohlcv, 100.0, "BUY")
        initial_sl = sl.current_stoploss["stoploss_price"]

        # Price dropped — SL should not decrease
        result = sl.update_stoploss(ohlcv, 80.0, "BUY")
        assert result["stoploss_price"] >= initial_sl

    def test_trailing_down_for_sell(self, ohlcv):
        sl = self._make()
        sl.calculate_initial_stoploss(ohlcv, 110.0, "SELL")
        initial_sl = sl.current_stoploss["stoploss_price"]

        result = sl.update_stoploss(ohlcv, 90.0, "SELL")
        assert result["stoploss_price"] <= initial_sl
        assert result["stoploss_type"] in ("TRAILING_DOWN", "MAINTAINED")

    def test_breach_detected_buy(self, ohlcv):
        sl = self._make()
        sl.calculate_initial_stoploss(ohlcv, 100.0, "BUY")
        stop = sl.current_stoploss["stoploss_price"]

        breach = sl.check_stoploss_breach(stop - 1)  # price below SL
        assert breach["is_breached"] is True
        assert breach["breach_type"] == "STOPLOSS_HIT"

    def test_no_breach(self, ohlcv):
        sl = self._make()
        sl.calculate_initial_stoploss(ohlcv, 100.0, "BUY")
        stop = sl.current_stoploss["stoploss_price"]

        breach = sl.check_stoploss_breach(stop + 10)  # price well above SL
        assert breach["is_breached"] is False

    def test_breach_detected_sell(self, ohlcv):
        sl = self._make()
        sl.calculate_initial_stoploss(ohlcv, 100.0, "SELL")
        stop = sl.current_stoploss["stoploss_price"]

        breach = sl.check_stoploss_breach(stop + 1)
        assert breach["is_breached"] is True

    def test_no_stoploss_breach_check(self):
        sl = self._make()
        breach = sl.check_stoploss_breach(100.0)
        assert breach["is_breached"] is False
        assert breach["breach_type"] == "NO_STOPLOSS"

    def test_breakeven_buy(self):
        sl = self._make()
        be = sl.get_breakeven_stoploss(100.0, "BUY")
        assert be > 100.0  # slightly above entry

    def test_breakeven_sell(self):
        sl = self._make()
        be = sl.get_breakeven_stoploss(100.0, "SELL")
        assert be < 100.0  # slightly below entry

    def test_should_move_to_breakeven(self):
        sl = self._make(breakeven_threshold=0.02)
        assert sl.should_move_to_breakeven(103.0, 100.0, "BUY") is True
        assert sl.should_move_to_breakeven(100.5, 100.0, "BUY") is False
        assert sl.should_move_to_breakeven(97.0, 100.0, "SELL") is True
        assert sl.should_move_to_breakeven(99.5, 100.0, "SELL") is False

    def test_risk_metrics_rr_ratio(self, ohlcv):
        sl = self._make(rr_target_multiplier=3.0)
        result = sl.calculate_initial_stoploss(ohlcv, 100.0, "BUY")
        rr = result["risk_metrics"]["risk_reward_ratio"]
        assert rr == 3.0  # configured 3:1

    def test_history_tracking(self, ohlcv):
        sl = self._make()
        sl.calculate_initial_stoploss(ohlcv, 100.0, "BUY")
        sl.update_stoploss(ohlcv, 105.0, "BUY")
        sl.update_stoploss(ohlcv, 110.0, "BUY")
        history = sl.get_stoploss_history()
        assert len(history) == 2  # two updates (initial doesn't go to history)

    def test_reset(self, ohlcv):
        sl = self._make()
        sl.calculate_initial_stoploss(ohlcv, 100.0, "BUY")
        sl.reset()
        assert sl.current_stoploss is None
        assert sl.stoploss_history == []
        assert sl.trend_direction == "NEUTRAL"

    def test_repr(self):
        sl = self._make()
        r = repr(sl)
        assert "SafeZoneStoploss" in r
        assert "TEST" in r
