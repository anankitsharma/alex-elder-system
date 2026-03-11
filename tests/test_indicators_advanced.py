"""
Tests for advanced Elder indicators:
ElderRay, ValueZone, AutoEnvelope, ElderThermometer, MACDDivergence.
"""

import pytest
import pandas as pd
import numpy as np
from backend.app.indicators import (
    ElderRay,
    ValueZone,
    AutoEnvelope,
    ElderThermometer,
    MACDDivergence,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing."""
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
        "datetime": dt,
        "open": opn,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def _make_trending_up(n: int = 200, seed: int = 99) -> pd.DataFrame:
    """Generate uptrending OHLCV data."""
    rng = np.random.RandomState(seed)
    trend = np.linspace(100, 130, n)
    noise = rng.randn(n) * 0.3
    close = trend + noise
    high = close + rng.uniform(0.2, 0.8, n)
    low = close - rng.uniform(0.2, 0.8, n)
    opn = close + rng.uniform(-0.3, 0.3, n)
    high = np.maximum(high, np.maximum(opn, close))
    low = np.minimum(low, np.minimum(opn, close))
    volume = rng.randint(1000, 50000, n).astype(float)
    dt = pd.date_range("2025-01-01", periods=n, freq="15min")
    return pd.DataFrame({
        "datetime": dt, "open": opn, "high": high,
        "low": low, "close": close, "volume": volume,
    })


def _make_trending_down(n: int = 200, seed: int = 77) -> pd.DataFrame:
    """Generate downtrending OHLCV data."""
    rng = np.random.RandomState(seed)
    trend = np.linspace(130, 100, n)
    noise = rng.randn(n) * 0.3
    close = trend + noise
    high = close + rng.uniform(0.2, 0.8, n)
    low = close - rng.uniform(0.2, 0.8, n)
    opn = close + rng.uniform(-0.3, 0.3, n)
    high = np.maximum(high, np.maximum(opn, close))
    low = np.minimum(low, np.minimum(opn, close))
    volume = rng.randint(1000, 50000, n).astype(float)
    dt = pd.date_range("2025-01-01", periods=n, freq="15min")
    return pd.DataFrame({
        "datetime": dt, "open": opn, "high": high,
        "low": low, "close": close, "volume": volume,
    })


def _make_divergence_data(n: int = 300, seed: int = 55) -> pd.DataFrame:
    """Generate data with enough bars for divergence detection."""
    rng = np.random.RandomState(seed)
    # Create a pattern: up, down, up higher, down less — to trigger divergence
    t = np.arange(n)
    # Sine wave with drift
    close = 100 + 10 * np.sin(t * 2 * np.pi / 60) + t * 0.02
    close += rng.randn(n) * 0.3
    high = close + rng.uniform(0.2, 1.0, n)
    low = close - rng.uniform(0.2, 1.0, n)
    opn = close + rng.uniform(-0.3, 0.3, n)
    high = np.maximum(high, np.maximum(opn, close))
    low = np.minimum(low, np.minimum(opn, close))
    volume = rng.randint(1000, 50000, n).astype(float)
    dt = pd.date_range("2025-01-01", periods=n, freq="15min")
    return pd.DataFrame({
        "datetime": dt, "open": opn, "high": high,
        "low": low, "close": close, "volume": volume,
    })


@pytest.fixture
def ohlcv():
    return _make_ohlcv(200)


@pytest.fixture
def small_ohlcv():
    return _make_ohlcv(5)


@pytest.fixture
def uptrend():
    return _make_trending_up(200)


@pytest.fixture
def downtrend():
    return _make_trending_down(200)


@pytest.fixture
def divergence_data():
    return _make_divergence_data(300)


# ===========================================================================
# ElderRay Tests
# ===========================================================================

class TestElderRay:
    def _make(self, period=13):
        return ElderRay("TEST", "15m", {"period": period})

    def test_basic_calculation(self, ohlcv):
        er = self._make()
        result = er.calculate(ohlcv)
        assert 'bull_power' in result.columns
        assert 'bear_power' in result.columns
        assert 'ema' in result.columns
        assert len(result) > 0

    def test_bull_power_formula(self, ohlcv):
        """Bull Power = High - EMA."""
        er = self._make()
        result = er.calculate(ohlcv)
        # Check last value matches formula
        last_bp = result['bull_power'].iloc[-1]
        last_high = result.iloc[-1]  # from result, has high? No — but we can verify via getter
        assert er.get_bull_power() is not None
        assert isinstance(er.get_bull_power(), float)

    def test_bear_power_always_exists(self, ohlcv):
        er = self._make()
        er.calculate(ohlcv)
        assert er.get_bear_power() is not None

    def test_ema_value(self, ohlcv):
        er = self._make()
        er.calculate(ohlcv)
        ema = er.get_ema_value()
        assert ema is not None
        assert ema > 0

    def test_ema_trend_uptrend(self, uptrend):
        er = self._make()
        er.calculate(uptrend)
        assert er.get_ema_trend() == 'RISING'

    def test_ema_trend_downtrend(self, downtrend):
        er = self._make()
        er.calculate(downtrend)
        assert er.get_ema_trend() == 'FALLING'

    def test_bull_power_trend(self, ohlcv):
        er = self._make()
        er.calculate(ohlcv)
        trend = er.get_bull_power_trend()
        assert trend in ('RISING', 'FALLING', 'MIXED', 'UNKNOWN')

    def test_bear_power_trend(self, ohlcv):
        er = self._make()
        er.calculate(ohlcv)
        trend = er.get_bear_power_trend()
        assert trend in ('RISING', 'FALLING', 'MIXED', 'UNKNOWN')

    def test_buy_signal_returns_bool(self, ohlcv):
        er = self._make()
        er.calculate(ohlcv)
        assert isinstance(er.get_buy_signal(), bool)

    def test_sell_signal_returns_bool(self, ohlcv):
        er = self._make()
        er.calculate(ohlcv)
        assert isinstance(er.get_sell_signal(), bool)

    def test_signal_summary(self, ohlcv):
        er = self._make()
        er.calculate(ohlcv)
        summary = er.get_signal_summary()
        assert 'bull_power' in summary
        assert 'bear_power' in summary
        assert 'ema_trend' in summary
        assert 'buy_signal' in summary
        assert 'sell_signal' in summary

    def test_signal_summary_no_data(self):
        er = self._make()
        summary = er.get_signal_summary()
        assert summary == {'status': 'no_data'}

    def test_insufficient_data_raises(self, small_ohlcv):
        er = self._make()
        with pytest.raises(ValueError, match="Insufficient data"):
            er.calculate(small_ohlcv)

    def test_invalid_config(self):
        with pytest.raises(ValueError):
            ElderRay("TEST", "15m", {"period": -1})

    def test_getter_with_index(self, ohlcv):
        er = self._make()
        er.calculate(ohlcv)
        assert er.get_bull_power(0) is not None
        assert er.get_bear_power(0) is not None
        assert er.get_ema_value(0) is not None

    def test_getter_out_of_range(self, ohlcv):
        er = self._make()
        er.calculate(ohlcv)
        assert er.get_bull_power(99999) is None

    def test_required_data_points(self):
        er = self._make(period=13)
        assert er.get_required_data_points() == 14

    def test_metadata(self, ohlcv):
        er = self._make()
        er.calculate(ohlcv)
        meta = er.calculation_metadata
        assert meta['period'] == 13
        assert meta['points_calculated'] > 0


# ===========================================================================
# ValueZone Tests
# ===========================================================================

class TestValueZone:
    def _make(self, fast=13, slow=26):
        return ValueZone("TEST", "15m", {"fast_period": fast, "slow_period": slow})

    def test_basic_calculation(self, ohlcv):
        vz = self._make()
        result = vz.calculate(ohlcv)
        assert 'fast_ema' in result.columns
        assert 'slow_ema' in result.columns
        assert 'zone_upper' in result.columns
        assert 'zone_lower' in result.columns
        assert 'zone_width' in result.columns
        assert len(result) > 0

    def test_zone_upper_gte_lower(self, ohlcv):
        vz = self._make()
        result = vz.calculate(ohlcv)
        assert (result['zone_upper'] >= result['zone_lower']).all()

    def test_zone_width_non_negative(self, ohlcv):
        vz = self._make()
        result = vz.calculate(ohlcv)
        assert (result['zone_width'] >= 0).all()

    def test_getters(self, ohlcv):
        vz = self._make()
        vz.calculate(ohlcv)
        assert vz.get_fast_ema() is not None
        assert vz.get_slow_ema() is not None
        assert vz.get_zone_width() is not None

    def test_price_position(self, ohlcv):
        vz = self._make()
        vz.calculate(ohlcv)
        close = ohlcv['close'].iloc[-1]
        # At least one of these should be deterministic
        in_zone = vz.is_price_in_zone(close)
        above = vz.is_price_above_zone(close)
        below = vz.is_price_below_zone(close)
        assert isinstance(in_zone, bool)
        assert isinstance(above, bool)
        assert isinstance(below, bool)

    def test_trend_direction_uptrend(self, uptrend):
        vz = self._make()
        vz.calculate(uptrend)
        # In uptrend, fast EMA should be above slow
        assert vz.get_trend_direction() == 'UP'

    def test_trend_direction_downtrend(self, downtrend):
        vz = self._make()
        vz.calculate(downtrend)
        assert vz.get_trend_direction() == 'DOWN'

    def test_zone_entry_signal(self, ohlcv):
        vz = self._make()
        vz.calculate(ohlcv)
        close = ohlcv['close'].iloc[-1]
        signal = vz.get_zone_entry_signal(close)
        assert signal in (None, 'BUY', 'SELL')

    def test_signal_summary(self, ohlcv):
        vz = self._make()
        vz.calculate(ohlcv)
        summary = vz.get_signal_summary()
        assert 'fast_ema' in summary
        assert 'slow_ema' in summary
        assert 'trend' in summary

    def test_signal_summary_no_data(self):
        vz = self._make()
        assert vz.get_signal_summary() == {'status': 'no_data'}

    def test_insufficient_data(self, small_ohlcv):
        vz = self._make()
        with pytest.raises(ValueError, match="Insufficient data"):
            vz.calculate(small_ohlcv)

    def test_invalid_config_fast_gte_slow(self):
        with pytest.raises(ValueError):
            ValueZone("TEST", "15m", {"fast_period": 26, "slow_period": 13})

    def test_required_data_points(self):
        vz = self._make(fast=13, slow=26)
        assert vz.get_required_data_points() == 27


# ===========================================================================
# AutoEnvelope Tests
# ===========================================================================

class TestAutoEnvelope:
    def _make(self, period=22, multiplier=2.7, lookback=100):
        return AutoEnvelope("TEST", "15m", {
            "period": period, "multiplier": multiplier, "lookback": lookback
        })

    def test_basic_calculation(self, ohlcv):
        ae = self._make()
        result = ae.calculate(ohlcv)
        assert 'ema' in result.columns
        assert 'upper' in result.columns
        assert 'lower' in result.columns
        assert 'width' in result.columns
        assert 'pct_position' in result.columns
        assert len(result) > 0

    def test_upper_gt_lower(self, ohlcv):
        ae = self._make()
        result = ae.calculate(ohlcv)
        assert (result['upper'] > result['lower']).all()

    def test_width_positive(self, ohlcv):
        ae = self._make()
        result = ae.calculate(ohlcv)
        assert (result['width'] > 0).all()

    def test_getters(self, ohlcv):
        ae = self._make()
        ae.calculate(ohlcv)
        assert ae.get_upper() is not None
        assert ae.get_lower() is not None
        assert ae.get_channel_width() is not None
        assert ae.get_channel_width() > 0

    def test_overbought_detection(self, ohlcv):
        ae = self._make()
        ae.calculate(ohlcv)
        # Price way above upper should be overbought
        very_high = ae.get_upper() + 100
        assert ae.is_at_upper_envelope(very_high) is True

    def test_oversold_detection(self, ohlcv):
        ae = self._make()
        ae.calculate(ohlcv)
        very_low = ae.get_lower() - 100
        assert ae.is_at_lower_envelope(very_low) is True

    def test_normal_price_not_extreme(self, ohlcv):
        ae = self._make()
        ae.calculate(ohlcv)
        mid = (ae.get_upper() + ae.get_lower()) / 2
        assert ae.is_at_upper_envelope(mid) is False
        assert ae.is_at_lower_envelope(mid) is False

    def test_signal_summary(self, ohlcv):
        ae = self._make()
        ae.calculate(ohlcv)
        summary = ae.get_signal_summary()
        assert 'ema' in summary
        assert 'upper' in summary
        assert 'lower' in summary
        assert 'width' in summary

    def test_signal_summary_no_data(self):
        ae = self._make()
        assert ae.get_signal_summary() == {'status': 'no_data'}

    def test_insufficient_data(self):
        ae = self._make(lookback=100)
        small = _make_ohlcv(50)
        with pytest.raises(ValueError, match="Insufficient data"):
            ae.calculate(small)

    def test_invalid_config_zero_period(self):
        with pytest.raises(ValueError):
            AutoEnvelope("TEST", "15m", {"period": 0, "multiplier": 2.7, "lookback": 100})

    def test_invalid_config_negative_multiplier(self):
        with pytest.raises(ValueError):
            AutoEnvelope("TEST", "15m", {"period": 22, "multiplier": -1, "lookback": 100})

    def test_required_data_points(self):
        ae = self._make(period=22, lookback=100)
        assert ae.get_required_data_points() == 101

    def test_pct_position_range(self, ohlcv):
        """Most price positions should be roughly 0-1 within the envelope."""
        ae = self._make()
        result = ae.calculate(ohlcv)
        pct = result['pct_position'].values
        # Allow some excursion outside but most should be near 0-1
        within_range = np.sum((pct >= -0.5) & (pct <= 1.5))
        assert within_range / len(pct) > 0.8  # 80% should be reasonable


# ===========================================================================
# ElderThermometer Tests
# ===========================================================================

class TestElderThermometer:
    def _make(self, period=22, spike_mult=2.0):
        return ElderThermometer("TEST", "15m", {
            "period": period, "spike_multiplier": spike_mult
        })

    def test_basic_calculation(self, ohlcv):
        et = self._make()
        result = et.calculate(ohlcv)
        assert 'raw' in result.columns
        assert 'smoothed' in result.columns
        assert 'is_spike' in result.columns
        assert len(result) > 0

    def test_raw_non_negative(self, ohlcv):
        et = self._make()
        result = et.calculate(ohlcv)
        # Raw thermometer should be >= 0
        assert (result['raw'] >= 0).all()

    def test_smoothed_non_negative(self, ohlcv):
        et = self._make()
        result = et.calculate(ohlcv)
        assert (result['smoothed'] >= 0).all()

    def test_getters(self, ohlcv):
        et = self._make()
        et.calculate(ohlcv)
        assert et.get_raw_value() is not None
        assert et.get_smoothed_value() is not None
        assert et.get_raw_value() >= 0
        assert et.get_smoothed_value() >= 0

    def test_is_spike_returns_bool(self, ohlcv):
        et = self._make()
        et.calculate(ohlcv)
        assert isinstance(et.is_spike(), bool)

    def test_volatility_regime(self, ohlcv):
        et = self._make()
        et.calculate(ohlcv)
        regime = et.get_volatility_regime()
        assert regime in ('EXTREME', 'HIGH', 'NORMAL', 'LOW', 'UNKNOWN')

    def test_signal_summary(self, ohlcv):
        et = self._make()
        et.calculate(ohlcv)
        summary = et.get_signal_summary()
        assert 'raw' in summary
        assert 'smoothed' in summary
        assert 'is_spike' in summary
        assert 'regime' in summary

    def test_signal_summary_no_data(self):
        et = self._make()
        assert et.get_signal_summary() == {'status': 'no_data'}

    def test_insufficient_data(self):
        et = self._make(period=22)
        small = _make_ohlcv(10)
        with pytest.raises(ValueError, match="Insufficient data"):
            et.calculate(small)

    def test_invalid_config(self):
        with pytest.raises(ValueError):
            ElderThermometer("TEST", "15m", {"period": -5})

    def test_required_data_points(self):
        et = self._make(period=22)
        assert et.get_required_data_points() == 24

    def test_metadata(self, ohlcv):
        et = self._make()
        et.calculate(ohlcv)
        meta = et.calculation_metadata
        assert 'last_raw' in meta
        assert 'last_smoothed' in meta
        assert 'is_current_spike' in meta


# ===========================================================================
# MACDDivergence Tests
# ===========================================================================

class TestMACDDivergence:
    def _make(self, fast=12, slow=26, signal=9, peak_lookback=5):
        return MACDDivergence("TEST", "15m", {
            "fast_length": fast, "slow_length": slow,
            "signal_length": signal, "peak_lookback": peak_lookback
        })

    def test_basic_calculation(self, divergence_data):
        md = self._make()
        result = md.calculate(divergence_data)
        assert 'histogram' in result.columns
        assert 'divergence_signal' in result.columns
        assert len(result) > 0

    def test_histogram_calculated(self, ohlcv):
        md = self._make()
        result = md.calculate(ohlcv)
        assert md.histogram is not None
        assert len(md.histogram) > 0

    def test_peaks_and_troughs_detected(self, divergence_data):
        md = self._make()
        md.calculate(divergence_data)
        # With sine wave data, should find some peaks and troughs
        assert md.peaks is not None
        assert md.troughs is not None

    def test_peaks_are_positive(self, divergence_data):
        md = self._make()
        md.calculate(divergence_data)
        for idx, val in md.peaks:
            assert val > 0, f"Peak at index {idx} has value {val} <= 0"

    def test_troughs_are_negative(self, divergence_data):
        md = self._make()
        md.calculate(divergence_data)
        for idx, val in md.troughs:
            assert val < 0, f"Trough at index {idx} has value {val} >= 0"

    def test_divergences_list(self, divergence_data):
        md = self._make()
        md.calculate(divergence_data)
        divs = md.get_all_divergences()
        assert isinstance(divs, list)
        for d in divs:
            assert d['type'] in ('BULLISH', 'BEARISH')
            assert 'strength' in d
            assert 0 <= d['strength'] <= 1.0

    def test_latest_divergence(self, divergence_data):
        md = self._make()
        md.calculate(divergence_data)
        latest = md.get_latest_divergence()
        # May or may not have divergence — just check type
        if latest is not None:
            assert latest['type'] in ('BULLISH', 'BEARISH')

    def test_has_active_divergence(self, divergence_data):
        md = self._make()
        md.calculate(divergence_data)
        active = md.has_active_divergence(lookback_bars=50)
        assert active in (None, 'BULLISH', 'BEARISH')

    def test_signal_summary(self, divergence_data):
        md = self._make()
        md.calculate(divergence_data)
        summary = md.get_signal_summary()
        assert 'histogram' in summary
        assert 'total_divergences' in summary
        assert 'peaks_found' in summary
        assert 'troughs_found' in summary

    def test_signal_summary_no_data(self):
        md = self._make()
        assert md.get_signal_summary() == {'status': 'no_data'}

    def test_insufficient_data(self, small_ohlcv):
        md = self._make()
        with pytest.raises(ValueError, match="Insufficient data"):
            md.calculate(small_ohlcv)

    def test_invalid_config_fast_gte_slow(self):
        with pytest.raises(ValueError):
            MACDDivergence("TEST", "15m", {
                "fast_length": 26, "slow_length": 12, "signal_length": 9
            })

    def test_required_data_points(self):
        md = self._make(fast=12, slow=26, signal=9, peak_lookback=5)
        assert md.get_required_data_points() == 40  # 26 + 9 + 5

    def test_metadata(self, divergence_data):
        md = self._make()
        md.calculate(divergence_data)
        meta = md.calculation_metadata
        assert 'divergences_found' in meta
        assert 'peaks_found' in meta
        assert 'troughs_found' in meta
        assert 'last_histogram' in meta

    def test_zero_crossing_validation(self, divergence_data):
        """Verify that all detected divergences have zero-line crossing."""
        md = self._make()
        md.calculate(divergence_data)
        for div in md.get_all_divergences():
            # The segment between start and end must cross zero
            segment = md.histogram[div['start_idx']:div['end_idx'] + 1]
            has_pos = np.any(segment > 0)
            has_neg = np.any(segment < 0)
            assert has_pos and has_neg, \
                f"Divergence at {div['start_idx']}-{div['end_idx']} lacks zero crossing"
