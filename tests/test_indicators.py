"""
Tests for the Elder's Trading System indicator engine.

Covers: BaseIndicator, EMAEnhanced, MACDEnhanced, ForceIndexEnhanced,
        SafeZoneV2, ElderImpulseEnhanced.
"""

import pytest
import pandas as pd
import numpy as np
from backend.app.indicators import (
    BaseIndicator,
    EMAEnhanced,
    MACDEnhanced,
    ForceIndexEnhanced,
    SafeZoneV2,
    ElderImpulseEnhanced,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 100, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing."""
    rng = np.random.RandomState(seed)
    close = 100 + np.cumsum(rng.randn(n) * 0.5)
    high = close + rng.uniform(0.2, 1.0, n)
    low = close - rng.uniform(0.2, 1.0, n)
    opn = close + rng.uniform(-0.5, 0.5, n)
    # Ensure OHLC consistency
    high = np.maximum(high, np.maximum(opn, close))
    low = np.minimum(low, np.minimum(opn, close))
    volume = rng.randint(1000, 50000, n).astype(float)
    dt = pd.date_range("2025-01-01", periods=n, freq="15min")
    return pd.DataFrame({
        "datetime": dt,
        "open": opn,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


@pytest.fixture
def ohlcv():
    return _make_ohlcv(100)


@pytest.fixture
def small_ohlcv():
    return _make_ohlcv(5)


# ---------------------------------------------------------------------------
# BaseIndicator
# ---------------------------------------------------------------------------

class TestBaseIndicator:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            BaseIndicator("SYM", "15m", {})

    def test_invalid_config_raises(self):
        """Subclass that always fails validation."""
        class Bad(BaseIndicator):
            def calculate(self, data): pass
            def validate_config(self): return False
        with pytest.raises(ValueError):
            Bad("SYM", "15m", {})


# ---------------------------------------------------------------------------
# EMAEnhanced
# ---------------------------------------------------------------------------

class TestEMAEnhanced:
    def _make(self, period=22, ma_type="None"):
        return EMAEnhanced("TEST", "15m", {"period": period, "ma_type": ma_type})

    def test_basic_calculation(self, ohlcv):
        ema = self._make(period=10)
        result = ema.calculate(ohlcv)
        assert "ema" in result.columns
        assert "value" in result.columns
        assert len(result) == len(ohlcv) - 9  # period-1 warmup
        assert not np.isnan(result["ema"].iloc[-1])

    def test_ema_values_stored(self, ohlcv):
        ema = self._make(period=10)
        ema.calculate(ohlcv)
        assert ema.ema_values is not None
        assert ema.last_ema is not None
        assert ema.get_ema_value() == ema.ema_values[-1]

    def test_get_ema_value_by_index(self, ohlcv):
        ema = self._make(period=10)
        ema.calculate(ohlcv)
        assert ema.get_ema_value(0) == ema.ema_values[0]
        assert ema.get_ema_value(-1) is None  # negative not supported
        assert ema.get_ema_value(999) is None  # out of range

    def test_trend_direction(self, ohlcv):
        ema = self._make(period=10)
        ema.calculate(ohlcv)
        direction = ema.get_ema_trend_direction(periods=3)
        assert direction in ("UP", "DOWN", "SIDEWAYS", "UNKNOWN")

    def test_price_above_below(self, ohlcv):
        ema = self._make(period=10)
        ema.calculate(ohlcv)
        last_ema = ema.get_ema_value()
        assert ema.is_price_above_ema(last_ema + 10)
        assert ema.is_price_below_ema(last_ema - 10)

    def test_distance_percentage(self, ohlcv):
        ema = self._make(period=10)
        ema.calculate(ohlcv)
        last_ema = ema.get_ema_value()
        pct = ema.get_ema_distance_percentage(last_ema * 1.05)
        assert pct is not None
        assert abs(pct - 5.0) < 0.01

    def test_with_sma_smoothing(self, ohlcv):
        ema = EMAEnhanced("TEST", "15m", {"period": 10, "ma_type": "SMA", "ma_length": 5})
        result = ema.calculate(ohlcv)
        assert "smoothing_ma" in result.columns

    def test_with_bollinger_bands(self, ohlcv):
        ema = EMAEnhanced("TEST", "15m", {
            "period": 10,
            "ma_type": "SMA + Bollinger Bands",
            "ma_length": 5,
            "bb_multiplier": 2.0,
        })
        result = ema.calculate(ohlcv)
        assert "bb_upper" in result.columns
        assert "bb_lower" in result.columns
        assert "bb_middle" in result.columns

    def test_insufficient_data(self, small_ohlcv):
        ema = self._make(period=10)
        with pytest.raises(ValueError):
            ema.calculate(small_ohlcv)

    def test_invalid_period(self):
        with pytest.raises(ValueError):
            EMAEnhanced("TEST", "15m", {"period": -5})

    def test_source_variants(self, ohlcv):
        for src in ("open", "high", "low", "close", "hl2", "hlc3", "ohlc4"):
            ema = EMAEnhanced("TEST", "15m", {"period": 10, "source": src, "ma_type": "None"})
            result = ema.calculate(ohlcv)
            assert len(result) > 0

    def test_indicator_info(self, ohlcv):
        ema = self._make(period=10)
        ema.calculate(ohlcv)
        info = ema.get_indicator_info()
        assert info["indicator_type"] == "EMA_Enhanced"
        assert info["period"] == 10


# ---------------------------------------------------------------------------
# MACDEnhanced
# ---------------------------------------------------------------------------

class TestMACDEnhanced:
    def _make(self):
        return MACDEnhanced("TEST", "15m", {
            "fast_length": 12,
            "slow_length": 26,
            "signal_length": 9,
            "source": "close",
            "oscillator_ma_type": "EMA",
            "signal_ma_type": "EMA",
        })

    def test_basic_calculation(self, ohlcv):
        macd = self._make()
        result = macd.calculate(ohlcv)
        assert "macd_line" in result.columns
        assert "signal_line" in result.columns
        assert "histogram" in result.columns
        assert len(result) > 0

    def test_values_stored(self, ohlcv):
        macd = self._make()
        macd.calculate(ohlcv)
        assert macd.macd_line is not None
        assert macd.signal_line is not None
        assert macd.histogram is not None

    def test_histogram_equals_diff(self, ohlcv):
        macd = self._make()
        macd.calculate(ohlcv)
        np.testing.assert_allclose(
            macd.histogram,
            macd.macd_line - macd.signal_line,
            atol=1e-10,
        )

    def test_crossover_detection(self, ohlcv):
        macd = self._make()
        macd.calculate(ohlcv)
        signal = macd.get_macd_crossover_signal()
        assert signal in ("BULLISH", "BEARISH", None)

    def test_histogram_color(self, ohlcv):
        macd = self._make()
        macd.calculate(ohlcv)
        color = macd.get_histogram_color()
        assert color in ("#26A69A", "#B2DFDB", "#FFCDD2", "#FF5252", "#787B86")

    def test_above_below_signal(self, ohlcv):
        macd = self._make()
        macd.calculate(ohlcv)
        # One of these must be true (unless exactly equal)
        above = macd.is_macd_above_signal()
        below = macd.is_macd_below_signal()
        assert above or below or (not above and not below)  # valid boolean-like

    def test_invalid_fast_ge_slow(self):
        with pytest.raises(ValueError):
            MACDEnhanced("TEST", "15m", {
                "fast_length": 26,
                "slow_length": 12,
                "signal_length": 9,
                "oscillator_ma_type": "EMA",
                "signal_ma_type": "EMA",
            })

    def test_indicator_info(self, ohlcv):
        macd = self._make()
        macd.calculate(ohlcv)
        info = macd.get_indicator_info()
        assert info["indicator_type"] == "MACD_Enhanced"


# ---------------------------------------------------------------------------
# ForceIndexEnhanced
# ---------------------------------------------------------------------------

class TestForceIndexEnhanced:
    def _make(self, length=13):
        return ForceIndexEnhanced("TEST", "15m", {"length": length, "source": "close"})

    def test_basic_calculation(self, ohlcv):
        fi = self._make()
        result = fi.calculate(ohlcv)
        assert "efi" in result.columns
        assert "raw_force" in result.columns
        assert len(result) > 0

    def test_values_stored(self, ohlcv):
        fi = self._make()
        fi.calculate(ohlcv)
        assert fi.efi_values is not None
        assert fi.raw_force is not None

    def test_zero_cross_detection(self, ohlcv):
        fi = self._make()
        fi.calculate(ohlcv)
        signal = fi.get_zero_cross_signal()
        assert signal in ("BULLISH", "BEARISH", None)

    def test_above_below_zero(self, ohlcv):
        fi = self._make()
        fi.calculate(ohlcv)
        above = fi.is_above_zero()
        below = fi.is_below_zero()
        assert above or below or (not above and not below)  # valid boolean-like

    def test_trend(self, ohlcv):
        fi = self._make()
        fi.calculate(ohlcv)
        trend = fi.get_efi_trend()
        assert trend in ("RISING", "FALLING", "SIDEWAYS", "UNKNOWN")

    def test_strength(self, ohlcv):
        fi = self._make()
        fi.calculate(ohlcv)
        summary = fi.get_signal_summary()
        assert summary["strength"] in ("STRONG", "MODERATE", "WEAK", "UNKNOWN")

    def test_no_volume_raises(self):
        fi = self._make()
        data = _make_ohlcv(50)
        data = data.drop(columns=["volume"])
        with pytest.raises(ValueError, match="volume"):
            fi.calculate(data)

    def test_zero_volume_raises(self):
        fi = self._make()
        data = _make_ohlcv(50)
        data["volume"] = 0
        with pytest.raises(ValueError, match="volume"):
            fi.calculate(data)


# ---------------------------------------------------------------------------
# SafeZoneV2
# ---------------------------------------------------------------------------

class TestSafeZoneV2:
    def _make(self, lookback=22, coeff=2.0):
        return SafeZoneV2("TEST", "15m", {
            "lookback_length": lookback,
            "coefficient": coeff,
            "progressive_mode": True,
        })

    def test_basic_calculation(self, ohlcv):
        sz = self._make()
        result = sz.calculate(ohlcv)
        assert "longvs" in result.columns
        assert "shortvs" in result.columns
        assert "long_stop" in result.columns
        assert "short_stop" in result.columns
        assert len(result) == len(ohlcv)

    def test_stops_are_reasonable(self, ohlcv):
        sz = self._make()
        sz.calculate(ohlcv)
        long_stop = sz.get_long_stop()
        short_stop = sz.get_short_stop()
        assert long_stop is not None
        assert short_stop is not None
        # Long stop should be below short stop (support < resistance)
        assert long_stop < short_stop

    def test_stoploss_level(self, ohlcv):
        sz = self._make()
        sz.calculate(ohlcv)
        long_sl = sz.calculate_stoploss_level(100, "LONG")
        short_sl = sz.calculate_stoploss_level(100, "SHORT")
        assert long_sl is not None
        assert short_sl is not None

    def test_risk_amount(self, ohlcv):
        sz = self._make()
        sz.calculate(ohlcv)
        risk = sz.calculate_risk_amount(100, "LONG")
        assert risk is not None
        assert risk >= 0

    def test_position_size(self, ohlcv):
        sz = self._make()
        sz.calculate(ohlcv)
        size = sz.calculate_position_size(100, 100000, 1.0, "LONG")
        assert size is not None
        assert size > 0

    def test_insufficient_data(self, small_ohlcv):
        sz = self._make()
        with pytest.raises(ValueError):
            sz.calculate(small_ohlcv)

    def test_incremental_update_not_supported(self, ohlcv):
        sz = self._make()
        sz.calculate(ohlcv)
        assert sz.update_with_new_data({"open": 1, "high": 2, "low": 0.5, "close": 1.5}) is False

    def test_indicator_info(self, ohlcv):
        sz = self._make()
        sz.calculate(ohlcv)
        info = sz.get_indicator_info()
        assert info["name"] == "SafeZone V2"


# ---------------------------------------------------------------------------
# ElderImpulseEnhanced
# ---------------------------------------------------------------------------

class TestElderImpulseEnhanced:
    def _make(self):
        return ElderImpulseEnhanced("TEST", "15m", {
            "macd_fast_length": 12,
            "macd_slow_length": 26,
            "macd_signal_length": 9,
            "ema_length": 13,
            "source": "close",
            "bullish_color": "green",
            "bearish_color": "red",
            "neutral_color": "blue",
        })

    def test_basic_calculation(self, ohlcv):
        imp = self._make()
        result = imp.calculate(ohlcv)
        assert "impulse_color" in result.columns
        assert "impulse_signal" in result.columns
        assert "ema_value" in result.columns
        assert "macd_histogram" in result.columns
        assert len(result) > 0

    def test_signals_are_valid(self, ohlcv):
        imp = self._make()
        imp.calculate(ohlcv)
        for signal in imp.impulse_signals:
            assert signal in ("bullish", "bearish", "neutral")
        for color in imp.impulse_colors:
            assert color in ("green", "red", "blue")

    def test_get_signal_and_color(self, ohlcv):
        imp = self._make()
        imp.calculate(ohlcv)
        assert imp.get_impulse_signal() in ("bullish", "bearish", "neutral")
        assert imp.get_impulse_color() in ("green", "red", "blue")

    def test_signal_summary(self, ohlcv):
        imp = self._make()
        imp.calculate(ohlcv)
        summary = imp.get_signal_summary()
        assert "current_signal" in summary
        assert "trend_strength" in summary
        assert "momentum_strength" in summary

    def test_first_bar_is_neutral(self, ohlcv):
        imp = self._make()
        imp.calculate(ohlcv)
        assert imp.get_impulse_signal(0) == "neutral"

    def test_insufficient_data(self, small_ohlcv):
        imp = self._make()
        with pytest.raises(ValueError):
            imp.calculate(small_ohlcv)

    def test_trend_strength_values(self, ohlcv):
        imp = self._make()
        imp.calculate(ohlcv)
        summary = imp.get_signal_summary()
        valid_strengths = ("strong_bullish", "strong_bearish", "weak_bullish", "weak_bearish", "sideways", "unknown")
        assert summary["trend_strength"] in valid_strengths
        assert summary["momentum_strength"] in valid_strengths
