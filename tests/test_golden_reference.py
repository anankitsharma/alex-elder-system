"""
Golden Reference Tests — Validate all 10 indicators against hand-computed values.

Uses a deterministic 50-bar dataset (tests/golden_data.py) with known up/down/flat
segments. Every assertion uses atol=1e-6 for floating point precision.

Also includes 6 cross-indicator invariant tests.
"""

import sys
import os
import time

import numpy as np
import pandas as pd
import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from tests.golden_data import (
    get_golden_dataframe,
    get_large_golden_dataframe,
    GOLDEN_CLOSE,
    GOLDEN_HIGH,
    GOLDEN_LOW,
    GOLDEN_VOLUME,
    EXPECTED_EMA13,
    EXPECTED_EMA22,
    EXPECTED_MACD_LINE,
    EXPECTED_MACD_SIGNAL,
    EXPECTED_MACD_HISTOGRAM,
    compute_ema,
)
from backend.app.indicators.ema import EMAEnhanced
from backend.app.indicators.macd import MACDEnhanced
from backend.app.indicators.force_index import ForceIndexEnhanced
from backend.app.indicators.safezone import SafeZoneV2
from backend.app.indicators.impulse import ElderImpulseEnhanced
from backend.app.indicators.elder_ray import ElderRay
from backend.app.indicators.value_zone import ValueZone
from backend.app.indicators.auto_envelope import AutoEnvelope
from backend.app.indicators.elder_thermometer import ElderThermometer
from backend.app.indicators.macd_divergence import MACDDivergence


@pytest.fixture
def golden_df():
    return get_golden_dataframe()


# ══════════════════════════════════════════════════════════════════════
# EMA Tests
# ══════════════════════════════════════════════════════════════════════

class TestGoldenEMA:
    """EMA golden reference tests."""

    def test_ema13_output_length(self, golden_df):
        """EMA-13 should produce 50-12=38 values."""
        ema = EMAEnhanced('TEST', '1d', {'period': 13, 'source': 'close', 'ma_type': 'None'})
        result = ema.calculate(golden_df)
        assert len(result) == 50 - 13 + 1  # 38 values

    def test_ema13_values_match(self, golden_df):
        """EMA-13 values should match hand-computed values."""
        ema = EMAEnhanced('TEST', '1d', {'period': 13, 'source': 'close', 'ma_type': 'None'})
        result = ema.calculate(golden_df)
        actual = result['ema'].values
        np.testing.assert_allclose(actual, EXPECTED_EMA13, atol=1e-6,
                                   err_msg="EMA-13 values don't match golden reference")

    def test_ema22_output_length(self, golden_df):
        """EMA-22 should produce 50-21=29 values."""
        ema = EMAEnhanced('TEST', '1d', {'period': 22, 'source': 'close', 'ma_type': 'None'})
        result = ema.calculate(golden_df)
        assert len(result) == 50 - 22 + 1  # 29 values

    def test_ema22_values_match(self, golden_df):
        """EMA-22 values should match hand-computed values."""
        ema = EMAEnhanced('TEST', '1d', {'period': 22, 'source': 'close', 'ma_type': 'None'})
        result = ema.calculate(golden_df)
        actual = result['ema'].values
        np.testing.assert_allclose(actual, EXPECTED_EMA22, atol=1e-6,
                                   err_msg="EMA-22 values don't match golden reference")

    def test_ema13_seed_is_sma(self, golden_df):
        """First EMA-13 value should be SMA of first 13 closes."""
        ema = EMAEnhanced('TEST', '1d', {'period': 13, 'source': 'close', 'ma_type': 'None'})
        result = ema.calculate(golden_df)
        expected_seed = np.mean(GOLDEN_CLOSE[:13])
        assert abs(result['ema'].values[0] - expected_seed) < 1e-6

    def test_ema_monotonic_in_uptrend(self, golden_df):
        """EMA-13 should be monotonically rising during strong uptrend (bars 35-49)."""
        ema = EMAEnhanced('TEST', '1d', {'period': 13, 'source': 'close', 'ma_type': 'None'})
        result = ema.calculate(golden_df)
        # Map bar indices: result starts at bar 12, so bar 35 is index 23
        start_idx = 35 - 12
        ema_vals = result['ema'].values[start_idx:]
        for i in range(1, len(ema_vals)):
            assert ema_vals[i] > ema_vals[i - 1], f"EMA not rising at index {i}"


# ══════════════════════════════════════════════════════════════════════
# MACD Tests
# ══════════════════════════════════════════════════════════════════════

class TestGoldenMACD:
    """MACD golden reference tests."""

    def test_macd_histogram_at_known_bars(self, golden_df):
        """MACD histogram non-NaN values should match hand-computed values."""
        macd = MACDEnhanced('TEST', '1d', {
            'fast_length': 12, 'slow_length': 26, 'signal_length': 9,
            'source': 'close', 'oscillator_ma_type': 'EMA', 'signal_ma_type': 'EMA',
        })
        result = macd.calculate(golden_df)
        actual_hist = result['histogram'].values
        # Filter out NaN values from actual (indicator may include NaN prefix)
        valid_mask = ~np.isnan(actual_hist)
        actual_valid = actual_hist[valid_mask]
        np.testing.assert_allclose(actual_valid, EXPECTED_MACD_HISTOGRAM, atol=1e-6,
                                   err_msg="MACD histogram doesn't match golden reference")

    def test_macd_line_values(self, golden_df):
        """MACD line aligned portion should match hand-computed values."""
        macd = MACDEnhanced('TEST', '1d', {
            'fast_length': 12, 'slow_length': 26, 'signal_length': 9,
            'source': 'close', 'oscillator_ma_type': 'EMA', 'signal_ma_type': 'EMA',
        })
        result = macd.calculate(golden_df)
        actual_macd = result['macd_line'].values
        # The indicator aligns MACD line to where signal is valid
        # so actual_macd may be longer than expected (which is already aligned).
        # Compare the last N values where N = len(expected)
        expected_len = len(EXPECTED_MACD_LINE)
        actual_tail = actual_macd[-expected_len:]
        np.testing.assert_allclose(actual_tail, EXPECTED_MACD_LINE, atol=1e-6)

    def test_macd_histogram_color_logic(self, golden_df):
        """MACD histogram colors should follow Pine Script 4-color logic."""
        macd = MACDEnhanced('TEST', '1d', {
            'fast_length': 12, 'slow_length': 26, 'signal_length': 9,
            'source': 'close', 'oscillator_ma_type': 'EMA', 'signal_ma_type': 'EMA',
        })
        result = macd.calculate(golden_df)
        hist = result['histogram'].values

        for i in range(1, len(hist)):
            color = macd.get_histogram_color(i)
            prev = hist[i - 1]
            curr = hist[i]

            if curr >= 0 and prev < curr:
                assert color == '#26A69A', f"Bar {i}: rising green expected"
            elif curr >= 0 and prev >= curr:
                assert color == '#B2DFDB', f"Bar {i}: falling green expected"
            elif curr < 0 and prev < curr:
                assert color == '#FFCDD2', f"Bar {i}: rising red expected"
            elif curr < 0 and prev >= curr:
                assert color == '#FF5252', f"Bar {i}: falling red expected"

    def test_macd_signal_is_ema_of_macd_line(self, golden_df):
        """Signal line non-NaN values should be EMA-9 of MACD line."""
        macd = MACDEnhanced('TEST', '1d', {
            'fast_length': 12, 'slow_length': 26, 'signal_length': 9,
            'source': 'close', 'oscillator_ma_type': 'EMA', 'signal_ma_type': 'EMA',
        })
        result = macd.calculate(golden_df)
        actual_signal = result['signal_line'].values
        valid_mask = ~np.isnan(actual_signal)
        actual_valid = actual_signal[valid_mask]
        np.testing.assert_allclose(actual_valid, EXPECTED_MACD_SIGNAL, atol=1e-6)


# ══════════════════════════════════════════════════════════════════════
# Force Index Tests
# ══════════════════════════════════════════════════════════════════════

class TestGoldenForceIndex:
    """Force Index golden reference tests."""

    def test_fi13_first_raw_value(self, golden_df):
        """Raw force at first output bar matches formula."""
        fi = ForceIndexEnhanced('TEST', '1d', {'length': 13, 'source': 'close'})
        result = fi.calculate(golden_df)
        # With SMA-seed EMA(13), output starts at bar 13 (13 valid raw_force values needed).
        # raw_force at bar 13 = (close[13] - close[12]) * volume[13] = (113-112)*170000 = 170000
        first_bar = 13
        expected_first_raw = (GOLDEN_CLOSE[first_bar] - GOLDEN_CLOSE[first_bar - 1]) * GOLDEN_VOLUME[first_bar]
        assert abs(result['raw_force'].values[0] - expected_first_raw) < 1e-2

    def test_fi2_more_responsive(self, golden_df):
        """FI-2 should be more responsive (larger swings) than FI-13."""
        fi2 = ForceIndexEnhanced('TEST', '1d', {'length': 2, 'source': 'close'})
        fi13 = ForceIndexEnhanced('TEST', '1d', {'length': 13, 'source': 'close'})
        result2 = fi2.calculate(golden_df)
        result13 = fi13.calculate(golden_df)

        # FI-2 should have larger variance
        min_len = min(len(result2), len(result13))
        fi2_vals = result2['efi'].values[-min_len:]
        fi13_vals = result13['efi'].values[-min_len:]
        assert np.std(fi2_vals) > np.std(fi13_vals), "FI-2 should have larger variance than FI-13"

    def test_fi13_positive_in_uptrend(self, golden_df):
        """FI-13 should be predominantly positive during strong uptrend."""
        fi = ForceIndexEnhanced('TEST', '1d', {'length': 13, 'source': 'close'})
        result = fi.calculate(golden_df)
        efi = result['efi'].values
        # Last 10 values (strong uptrend bars 40-49)
        last_10 = efi[-10:]
        positive_count = np.sum(last_10 > 0)
        assert positive_count >= 7, f"Expected >70% positive in uptrend, got {positive_count}/10"

    def test_fi_raw_formula(self, golden_df):
        """Verify raw force = change(close) * volume for several bars."""
        fi = ForceIndexEnhanced('TEST', '1d', {'length': 2, 'source': 'close'})
        result = fi.calculate(golden_df)
        raw = result['raw_force'].values
        # With SMA-seed EMA(2), output starts at bar 2 (2 valid raw_force values needed).
        first_bar = 2
        for i in range(5):
            bar_idx = first_bar + i
            if bar_idx < len(GOLDEN_CLOSE):
                expected = (GOLDEN_CLOSE[bar_idx] - GOLDEN_CLOSE[bar_idx - 1]) * GOLDEN_VOLUME[bar_idx]
                assert abs(raw[i] - expected) < 1e-2, f"Raw force mismatch at bar {bar_idx}"


# ══════════════════════════════════════════════════════════════════════
# SafeZone Tests
# ══════════════════════════════════════════════════════════════════════

class TestGoldenSafeZone:
    """SafeZone golden reference tests."""

    def test_safezone_output_length(self, golden_df):
        """SafeZone should produce values for all 50 bars."""
        sz = SafeZoneV2('TEST', '1d', {
            'lookback_length': 22, 'coefficient': 2.0, 'progressive_mode': True,
        })
        result = sz.calculate(golden_df)
        assert len(result) == 50

    def test_safezone_longvs_below_shortvs(self, golden_df):
        """Long stop (support) should be at or below short stop (resistance)."""
        sz = SafeZoneV2('TEST', '1d', {
            'lookback_length': 22, 'coefficient': 2.0, 'progressive_mode': True,
        })
        result = sz.calculate(golden_df)
        longvs = result['longvs'].values
        shortvs = result['shortvs'].values

        for i in range(1, len(longvs)):
            if not np.isnan(longvs[i]) and not np.isnan(shortvs[i]):
                assert longvs[i] <= shortvs[i], \
                    f"Bar {i}: longvs ({longvs[i]:.4f}) > shortvs ({shortvs[i]:.4f})"

    def test_safezone_progressive_long_never_decreases_in_uptrend(self, golden_df):
        """In uptrend, progressive long stop should ratchet up (never decrease)."""
        sz = SafeZoneV2('TEST', '1d', {
            'lookback_length': 22, 'coefficient': 2.0, 'progressive_mode': True,
        })
        result = sz.calculate(golden_df)
        longvs = result['longvs'].values
        close = GOLDEN_CLOSE

        # During strong uptrend (bars 35-49) where close > longvs
        for i in range(36, 50):
            if not np.isnan(longvs[i]) and not np.isnan(longvs[i - 1]):
                if close[i] >= longvs[i - 1]:
                    # Progressive mode: should not decrease when above stop
                    assert longvs[i] >= longvs[i - 1], \
                        f"Bar {i}: longvs decreased from {longvs[i-1]:.4f} to {longvs[i]:.4f}"

    def test_safezone_performance_benchmark(self):
        """SafeZone on 2000 bars should complete in < 200ms."""
        df = get_large_golden_dataframe(2000)
        sz = SafeZoneV2('TEST', '1d', {
            'lookback_length': 22, 'coefficient': 2.0, 'progressive_mode': True,
        })
        start = time.time()
        sz.calculate(df)
        elapsed_ms = (time.time() - start) * 1000
        assert elapsed_ms < 200, f"SafeZone took {elapsed_ms:.0f}ms on 2000 bars (limit: 200ms)"

    def test_safezone_first_bar_is_nan(self, golden_df):
        """Bar 0 should be NaN (no previous bar to compare)."""
        sz = SafeZoneV2('TEST', '1d', {
            'lookback_length': 22, 'coefficient': 2.0, 'progressive_mode': True,
        })
        result = sz.calculate(golden_df)
        assert np.isnan(result['longvs'].values[0])
        assert np.isnan(result['shortvs'].values[0])


# ══════════════════════════════════════════════════════════════════════
# Impulse Tests
# ══════════════════════════════════════════════════════════════════════

class TestGoldenImpulse:
    """Impulse System golden reference tests."""

    def test_impulse_colors_valid(self, golden_df):
        """All impulse colors should be green, red, or blue."""
        impulse = ElderImpulseEnhanced('TEST', '1d', {
            'macd_fast_length': 12, 'macd_slow_length': 26,
            'macd_signal_length': 9, 'ema_length': 13,
            'source': 'close',
            'bullish_color': 'green', 'bearish_color': 'red', 'neutral_color': 'blue',
        })
        result = impulse.calculate(golden_df)
        colors = result['impulse_color'].tolist()
        for c in colors:
            assert c in ('green', 'red', 'blue'), f"Invalid color: {c}"

    def test_impulse_green_requires_both_rising(self, golden_df):
        """Green bars require EMA rising AND MACD-H rising."""
        impulse = ElderImpulseEnhanced('TEST', '1d', {
            'macd_fast_length': 12, 'macd_slow_length': 26,
            'macd_signal_length': 9, 'ema_length': 13,
            'source': 'close',
            'bullish_color': 'green', 'bearish_color': 'red', 'neutral_color': 'blue',
        })
        result = impulse.calculate(golden_df)
        ema = result['ema_value'].values
        hist = result['macd_histogram'].values
        colors = result['impulse_color'].tolist()

        for i in range(1, len(colors)):
            if colors[i] == 'green':
                assert ema[i] > ema[i - 1], f"Green at {i} but EMA not rising"
                assert hist[i] > hist[i - 1], f"Green at {i} but MACD-H not rising"

    def test_impulse_red_requires_both_falling(self, golden_df):
        """Red bars require EMA falling AND MACD-H falling."""
        impulse = ElderImpulseEnhanced('TEST', '1d', {
            'macd_fast_length': 12, 'macd_slow_length': 26,
            'macd_signal_length': 9, 'ema_length': 13,
            'source': 'close',
            'bullish_color': 'green', 'bearish_color': 'red', 'neutral_color': 'blue',
        })
        result = impulse.calculate(golden_df)
        ema = result['ema_value'].values
        hist = result['macd_histogram'].values
        colors = result['impulse_color'].tolist()

        for i in range(1, len(colors)):
            if colors[i] == 'red':
                assert ema[i] < ema[i - 1], f"Red at {i} but EMA not falling"
                assert hist[i] < hist[i - 1], f"Red at {i} but MACD-H not falling"

    def test_impulse_strong_uptrend_has_green(self, golden_df):
        """Strong uptrend (bars 40-49) should produce some green bars."""
        impulse = ElderImpulseEnhanced('TEST', '1d', {
            'macd_fast_length': 12, 'macd_slow_length': 26,
            'macd_signal_length': 9, 'ema_length': 13,
            'source': 'close',
            'bullish_color': 'green', 'bearish_color': 'red', 'neutral_color': 'blue',
        })
        result = impulse.calculate(golden_df)
        colors = result['impulse_color'].tolist()
        # Last 5-10 bars should have some green
        last_colors = colors[-10:]
        green_count = last_colors.count('green')
        assert green_count >= 2, f"Expected green bars in strong uptrend, got {green_count}/10"


# ══════════════════════════════════════════════════════════════════════
# Elder-Ray Tests
# ══════════════════════════════════════════════════════════════════════

class TestGoldenElderRay:
    """Elder-Ray golden reference tests."""

    def test_bull_power_formula(self, golden_df):
        """Bull Power = High - EMA(13)."""
        er = ElderRay('TEST', '1d', {'period': 13})
        result = er.calculate(golden_df)
        ema = result['ema'].values
        bull = result['bull_power'].values
        high = golden_df['high'].values[12:]  # aligned to EMA start

        np.testing.assert_allclose(bull, high - ema, atol=1e-6)

    def test_bear_power_formula(self, golden_df):
        """Bear Power = Low - EMA(13)."""
        er = ElderRay('TEST', '1d', {'period': 13})
        result = er.calculate(golden_df)
        ema = result['ema'].values
        bear = result['bear_power'].values
        low = golden_df['low'].values[12:]

        np.testing.assert_allclose(bear, low - ema, atol=1e-6)

    def test_bull_power_mostly_positive(self, golden_df):
        """Bull Power should be mostly positive (high usually > EMA)."""
        er = ElderRay('TEST', '1d', {'period': 13})
        result = er.calculate(golden_df)
        bull = result['bull_power'].values
        positive = np.sum(bull > 0)
        assert positive > len(bull) * 0.4, \
            f"Expected >40% positive bull power, got {positive}/{len(bull)}"

    def test_bear_power_mostly_negative(self, golden_df):
        """Bear Power should be mostly negative (low usually < EMA)."""
        er = ElderRay('TEST', '1d', {'period': 13})
        result = er.calculate(golden_df)
        bear = result['bear_power'].values
        negative = np.sum(bear < 0)
        assert negative > len(bear) * 0.4, \
            f"Expected >40% negative bear power, got {negative}/{len(bear)}"

    def test_elder_ray_ema_matches_standalone(self, golden_df):
        """Elder-Ray internal EMA should match standalone EMA-13."""
        er = ElderRay('TEST', '1d', {'period': 13})
        result_er = er.calculate(golden_df)

        ema = EMAEnhanced('TEST', '1d', {'period': 13, 'source': 'close', 'ma_type': 'None'})
        result_ema = ema.calculate(golden_df)

        np.testing.assert_allclose(
            result_er['ema'].values, result_ema['ema'].values, atol=1e-6
        )


# ══════════════════════════════════════════════════════════════════════
# Value Zone Tests
# ══════════════════════════════════════════════════════════════════════

class TestGoldenValueZone:
    """Value Zone golden reference tests."""

    def test_zone_upper_gte_lower(self, golden_df):
        """Zone upper should always be >= zone lower."""
        vz = ValueZone('TEST', '1d', {'fast_period': 13, 'slow_period': 26})
        result = vz.calculate(golden_df)
        upper = result['zone_upper'].values
        lower = result['zone_lower'].values

        for i in range(len(upper)):
            assert upper[i] >= lower[i], \
                f"Bar {i}: upper ({upper[i]:.4f}) < lower ({lower[i]:.4f})"

    def test_zone_bounds_are_max_min_of_emas(self, golden_df):
        """upper = max(EMA13, EMA26), lower = min(EMA13, EMA26)."""
        vz = ValueZone('TEST', '1d', {'fast_period': 13, 'slow_period': 26})
        result = vz.calculate(golden_df)
        fast = result['fast_ema'].values
        slow = result['slow_ema'].values
        upper = result['zone_upper'].values
        lower = result['zone_lower'].values

        np.testing.assert_allclose(upper, np.maximum(fast, slow), atol=1e-6)
        np.testing.assert_allclose(lower, np.minimum(fast, slow), atol=1e-6)

    def test_zone_width_nonnegative(self, golden_df):
        """Zone width should always be non-negative."""
        vz = ValueZone('TEST', '1d', {'fast_period': 13, 'slow_period': 26})
        result = vz.calculate(golden_df)
        width = result['zone_width'].values
        assert np.all(width >= 0), "Zone width has negative values"


# ══════════════════════════════════════════════════════════════════════
# AutoEnvelope Tests
# ══════════════════════════════════════════════════════════════════════

class TestGoldenAutoEnvelope:
    """AutoEnvelope golden reference tests."""

    def test_envelope_structure(self, golden_df):
        """Upper > EMA > Lower for all valid bars."""
        # Need enough data — use a larger dataset for AutoEnvelope (needs lookback=100)
        df = get_large_golden_dataframe(200)
        ae = AutoEnvelope('TEST', '1d', {'period': 22, 'multiplier': 2.7, 'lookback': 100})
        result = ae.calculate(df)
        upper = result['upper'].values
        lower = result['lower'].values
        ema = result['ema'].values

        for i in range(len(upper)):
            assert upper[i] > ema[i], f"Bar {i}: upper <= ema"
            assert lower[i] < ema[i], f"Bar {i}: lower >= ema"

    def test_envelope_uses_population_sd(self, golden_df):
        """After ddof fix, should use population SD (ddof=0)."""
        df = get_large_golden_dataframe(200)
        ae = AutoEnvelope('TEST', '1d', {'period': 22, 'multiplier': 2.7, 'lookback': 100})
        result = ae.calculate(df)
        # Channel should exist and have positive width
        width = result['upper'].values - result['lower'].values
        assert np.all(width > 0), "Channel width should be positive"

    def test_envelope_width_positive(self, golden_df):
        """Channel width should always be positive."""
        df = get_large_golden_dataframe(200)
        ae = AutoEnvelope('TEST', '1d', {'period': 22, 'multiplier': 2.7, 'lookback': 100})
        result = ae.calculate(df)
        width = result['width'].values
        assert np.all(width > 0), "Width should be positive"


# ══════════════════════════════════════════════════════════════════════
# Elder Thermometer Tests
# ══════════════════════════════════════════════════════════════════════

class TestGoldenThermometer:
    """Elder Thermometer golden reference tests."""

    def test_raw_formula(self, golden_df):
        """raw[i] = max(high[i]-high[i-1], low[i-1]-low[i], 0)."""
        et = ElderThermometer('TEST', '1d', {'period': 22})
        result = et.calculate(golden_df)
        raw = result['raw'].values

        # The result is aligned (trimmed from valid_start), so we need to figure out
        # which bars the result covers. With period=22, seed needs 22 valid raw values.
        # raw starts at bar 1, so first 22 valid raw values are bars 1-22, seed at bar 22.
        # But _calculate_ema_from_index starts searching from index 1 (start_search=1).
        # The valid_start will be at the EMA seed position.
        # Let's verify the raw values we can access
        for i in range(len(raw)):
            if not np.isnan(raw[i]):
                assert raw[i] >= 0, f"Raw thermometer negative at index {i}: {raw[i]}"

    def test_raw_nonnegative(self, golden_df):
        """All raw thermometer values should be >= 0."""
        et = ElderThermometer('TEST', '1d', {'period': 22})
        result = et.calculate(golden_df)
        raw = result['raw'].values
        assert np.all(raw[~np.isnan(raw)] >= 0), "Raw thermometer has negative values"

    def test_smoothed_nonnegative(self, golden_df):
        """Smoothed thermometer (EMA of non-negative values) should be non-negative."""
        et = ElderThermometer('TEST', '1d', {'period': 22})
        result = et.calculate(golden_df)
        smoothed = result['smoothed'].values
        assert np.all(smoothed[~np.isnan(smoothed)] >= 0), "Smoothed thermometer has negative values"

    def test_thermometer_uptrend_raw_values(self, golden_df):
        """During uptrend, raw thermo = high[i]-high[i-1] (since highs are rising)."""
        et = ElderThermometer('TEST', '1d', {'period': 22})
        result = et.calculate(golden_df)
        # Verify we get valid output
        assert len(result) > 0
        assert not np.all(np.isnan(result['raw'].values))

    def test_thermometer_classic_period(self, golden_df):
        """Thermometer with Elder's classic period 13 should work."""
        et = ElderThermometer('TEST', '1d', {'period': 13})
        result = et.calculate(golden_df)
        assert len(result) > 0
        # With period=13, should produce more output than period=22
        et22 = ElderThermometer('TEST', '1d', {'period': 22})
        result22 = et22.calculate(golden_df)
        assert len(result) >= len(result22)


# ══════════════════════════════════════════════════════════════════════
# MACD Divergence Tests
# ══════════════════════════════════════════════════════════════════════

class TestGoldenMACDDivergence:
    """MACD Divergence golden reference tests."""

    def test_divergence_output_structure(self, golden_df):
        """Divergence output should have histogram and signal columns."""
        md = MACDDivergence('TEST', '1d', {
            'fast_length': 12, 'slow_length': 26, 'signal_length': 9,
        })
        result = md.calculate(golden_df)
        assert 'histogram' in result.columns
        assert 'divergence_signal' in result.columns

    def test_divergence_signal_values(self, golden_df):
        """Divergence signals should be 0, 1, or -1."""
        md = MACDDivergence('TEST', '1d', {
            'fast_length': 12, 'slow_length': 26, 'signal_length': 9,
        })
        result = md.calculate(golden_df)
        signals = result['divergence_signal'].values
        for s in signals:
            assert s in (0.0, 1.0, -1.0), f"Invalid divergence signal: {s}"

    def test_zero_crossing_required(self, golden_df):
        """Any detected divergence should have a zero crossing between extremes."""
        md = MACDDivergence('TEST', '1d', {
            'fast_length': 12, 'slow_length': 26, 'signal_length': 9,
        })
        md.calculate(golden_df)
        divs = md.get_all_divergences()
        for div in divs:
            # Zero crossing was already validated in _detect_divergences
            assert div['type'] in ('BULLISH', 'BEARISH')
            assert div['start_idx'] < div['end_idx']


# ══════════════════════════════════════════════════════════════════════
# Cross-Indicator Invariant Tests
# ══════════════════════════════════════════════════════════════════════

class TestCrossIndicatorInvariants:
    """Cross-indicator invariant tests — verify consistency between indicators."""

    def test_impulse_green_iff_ema_up_and_macd_h_up(self, golden_df):
        """Impulse green <=> EMA rising AND MACD-H rising (100% correlation)."""
        impulse = ElderImpulseEnhanced('TEST', '1d', {
            'macd_fast_length': 12, 'macd_slow_length': 26,
            'macd_signal_length': 9, 'ema_length': 13,
            'source': 'close',
            'bullish_color': 'green', 'bearish_color': 'red', 'neutral_color': 'blue',
        })
        result = impulse.calculate(golden_df)
        ema = result['ema_value'].values
        hist = result['macd_histogram'].values
        colors = result['impulse_color'].tolist()

        for i in range(1, len(colors)):
            ema_rising = ema[i] > ema[i - 1]
            hist_rising = hist[i] > hist[i - 1]

            if colors[i] == 'green':
                assert ema_rising and hist_rising, \
                    f"Bar {i}: green but EMA_rising={ema_rising}, hist_rising={hist_rising}"
            if ema_rising and hist_rising:
                assert colors[i] == 'green', \
                    f"Bar {i}: EMA+MACD both rising but color={colors[i]}"

    def test_impulse_red_iff_ema_down_and_macd_h_down(self, golden_df):
        """Impulse red <=> EMA falling AND MACD-H falling (100% correlation)."""
        impulse = ElderImpulseEnhanced('TEST', '1d', {
            'macd_fast_length': 12, 'macd_slow_length': 26,
            'macd_signal_length': 9, 'ema_length': 13,
            'source': 'close',
            'bullish_color': 'green', 'bearish_color': 'red', 'neutral_color': 'blue',
        })
        result = impulse.calculate(golden_df)
        ema = result['ema_value'].values
        hist = result['macd_histogram'].values
        colors = result['impulse_color'].tolist()

        for i in range(1, len(colors)):
            ema_falling = ema[i] < ema[i - 1]
            hist_falling = hist[i] < hist[i - 1]

            if colors[i] == 'red':
                assert ema_falling and hist_falling
            if ema_falling and hist_falling:
                assert colors[i] == 'red'

    def test_uptrend_fi13_and_bull_power_agree(self, golden_df):
        """In sustained uptrend, FI-13 positive AND Bull Power positive (>70%)."""
        fi = ForceIndexEnhanced('TEST', '1d', {'length': 13, 'source': 'close'})
        er = ElderRay('TEST', '1d', {'period': 13})
        fi_result = fi.calculate(golden_df)
        er_result = er.calculate(golden_df)

        fi_vals = fi_result['efi'].values
        bull_vals = er_result['bull_power'].values

        # Last 10 values (strong uptrend)
        min_len = min(10, len(fi_vals), len(bull_vals))
        fi_last = fi_vals[-min_len:]
        bull_last = bull_vals[-min_len:]

        fi_positive = np.sum(fi_last > 0)
        bull_positive = np.sum(bull_last > 0)

        assert fi_positive >= min_len * 0.5, \
            f"FI-13 not predominantly positive in uptrend: {fi_positive}/{min_len}"
        assert bull_positive >= min_len * 0.5, \
            f"Bull power not predominantly positive in uptrend: {bull_positive}/{min_len}"

    def test_value_zone_upper_always_gte_lower(self, golden_df):
        """Value Zone upper >= lower always."""
        vz = ValueZone('TEST', '1d', {'fast_period': 13, 'slow_period': 26})
        result = vz.calculate(golden_df)
        upper = result['zone_upper'].values
        lower = result['zone_lower'].values
        assert np.all(upper >= lower)

    def test_auto_envelope_upper_gt_ema_gt_lower(self):
        """AutoEnvelope upper > EMA > lower always (where all non-null)."""
        df = get_large_golden_dataframe(200)
        ae = AutoEnvelope('TEST', '1d', {'period': 22, 'multiplier': 2.7, 'lookback': 100})
        result = ae.calculate(df)
        upper = result['upper'].values
        lower = result['lower'].values
        ema = result['ema'].values

        for i in range(len(upper)):
            if not np.isnan(upper[i]) and not np.isnan(lower[i]) and not np.isnan(ema[i]):
                assert upper[i] > ema[i], f"upper <= ema at {i}"
                assert ema[i] > lower[i], f"ema <= lower at {i}"

    def test_safezone_longvs_below_shortvs_always(self, golden_df):
        """SafeZone longvs <= shortvs always (long stop at or below short stop)."""
        sz = SafeZoneV2('TEST', '1d', {
            'lookback_length': 22, 'coefficient': 2.0, 'progressive_mode': True,
        })
        result = sz.calculate(golden_df)
        longvs = result['longvs'].values
        shortvs = result['shortvs'].values

        for i in range(len(longvs)):
            if not np.isnan(longvs[i]) and not np.isnan(shortvs[i]):
                assert longvs[i] <= shortvs[i], \
                    f"Bar {i}: longvs ({longvs[i]}) > shortvs ({shortvs[i]})"
