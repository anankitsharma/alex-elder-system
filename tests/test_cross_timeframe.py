"""
Tests for cross-timeframe signal validation.
"""

import sys
import os
import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.app.strategy.cross_timeframe_validator import (
    validate_screen_alignment,
    validate_impulse_consistency,
    validate_data_timeframe,
    validate_full_analysis,
    ValidationResult,
)
from backend.app.strategy.triple_screen import TripleScreenAnalysis


class TestValidateScreenAlignment:
    """Tests for screen alignment validation."""

    def test_bullish_tide_buy_signal_valid(self):
        """Bullish tide + BUY signal = valid."""
        s1 = {'tide': 'BULLISH', 'impulse_signal': 'bullish'}
        s2 = {'signal': 'BUY'}
        result = validate_screen_alignment(s1, s2)
        assert result.is_valid
        assert len(result.blocks) == 0

    def test_bearish_tide_sell_signal_valid(self):
        """Bearish tide + SELL signal = valid."""
        s1 = {'tide': 'BEARISH', 'impulse_signal': 'bearish'}
        s2 = {'signal': 'SELL'}
        result = validate_screen_alignment(s1, s2)
        assert result.is_valid

    def test_bullish_tide_sell_signal_blocked(self):
        """Bullish tide + SELL signal = blocked."""
        s1 = {'tide': 'BULLISH', 'impulse_signal': 'bullish'}
        s2 = {'signal': 'SELL'}
        result = validate_screen_alignment(s1, s2)
        assert not result.is_valid
        assert len(result.blocks) > 0

    def test_bearish_tide_buy_signal_blocked(self):
        """Bearish tide + BUY signal = blocked."""
        s1 = {'tide': 'BEARISH', 'impulse_signal': 'bearish'}
        s2 = {'signal': 'BUY'}
        result = validate_screen_alignment(s1, s2)
        assert not result.is_valid

    def test_red_impulse_blocks_buy(self):
        """Screen 1 RED impulse blocks all BUY signals."""
        s1 = {'tide': 'BEARISH', 'impulse_signal': 'bearish'}
        s2 = {'signal': 'BUY'}
        result = validate_screen_alignment(s1, s2)
        assert not result.is_valid
        assert any('RED' in b or 'BLOCKED' in b for b in result.blocks)

    def test_green_impulse_blocks_sell(self):
        """Screen 1 GREEN impulse blocks all SELL signals."""
        s1 = {'tide': 'BULLISH', 'impulse_signal': 'bullish'}
        s2 = {'signal': 'SELL'}
        result = validate_screen_alignment(s1, s2)
        assert not result.is_valid

    def test_neutral_tide_warns(self):
        """Neutral tide with signal produces warning."""
        s1 = {'tide': 'NEUTRAL', 'impulse_signal': 'neutral'}
        s2 = {'signal': 'BUY'}
        result = validate_screen_alignment(s1, s2)
        assert result.is_valid  # Not blocked, but warned
        assert len(result.warnings) > 0

    def test_no_signal_always_valid(self):
        """No signal (NONE) is always valid."""
        s1 = {'tide': 'BULLISH', 'impulse_signal': 'bullish'}
        s2 = {'signal': 'NONE'}
        result = validate_screen_alignment(s1, s2)
        assert result.is_valid


class TestValidateImpulseConsistency:
    """Tests for impulse consistency across screens."""

    def test_both_bullish_no_conflict(self):
        result = validate_impulse_consistency({
            'screen1': 'bullish', 'screen2': 'bullish',
        })
        assert result.is_valid
        assert len(result.blocks) == 0

    def test_both_bearish_no_conflict(self):
        result = validate_impulse_consistency({
            'screen1': 'bearish', 'screen2': 'bearish',
        })
        assert result.is_valid

    def test_conflicting_impulses_warned(self):
        result = validate_impulse_consistency({
            'screen1': 'bullish', 'screen2': 'bearish',
        })
        assert len(result.warnings) > 0 or len(result.blocks) > 0

    def test_s1_bearish_s2_bullish_blocked(self):
        """Screen 1 bearish overrides Screen 2 bullish."""
        result = validate_impulse_consistency({
            'screen1': 'bearish', 'screen2': 'bullish',
        })
        assert not result.is_valid

    def test_neutral_no_conflict(self):
        result = validate_impulse_consistency({
            'screen1': 'neutral', 'screen2': 'bullish',
        })
        assert result.is_valid


class TestValidateDataTimeframe:
    """Tests for data timeframe verification."""

    def test_daily_data_matches_1d(self):
        dt = pd.date_range('2024-01-01', periods=30, freq='D')
        df = pd.DataFrame({'datetime': dt, 'close': range(30)})
        assert validate_data_timeframe(df, '1d') is True

    def test_hourly_data_matches_1h(self):
        dt = pd.date_range('2024-01-01', periods=50, freq='h')
        df = pd.DataFrame({'datetime': dt, 'close': range(50)})
        assert validate_data_timeframe(df, '1h') is True

    def test_daily_data_doesnt_match_1h(self):
        dt = pd.date_range('2024-01-01', periods=30, freq='D')
        df = pd.DataFrame({'datetime': dt, 'close': range(30)})
        assert validate_data_timeframe(df, '1h') is False

    def test_insufficient_data_returns_true(self):
        """Too little data should not block."""
        dt = pd.date_range('2024-01-01', periods=2, freq='D')
        df = pd.DataFrame({'datetime': dt, 'close': [1, 2]})
        assert validate_data_timeframe(df, '1d') is True

    def test_unknown_timeframe_returns_true(self):
        dt = pd.date_range('2024-01-01', periods=10, freq='D')
        df = pd.DataFrame({'datetime': dt, 'close': range(10)})
        assert validate_data_timeframe(df, '3d') is True


class TestValidateFullAnalysis:
    """Tests for combined validation."""

    def test_valid_bullish_setup(self):
        s1 = {'tide': 'BULLISH', 'impulse_signal': 'bullish'}
        s2 = {'signal': 'BUY', 'impulse_signal': 'bullish'}
        result = validate_full_analysis(s1, s2)
        assert result.is_valid

    def test_conflicting_screens_blocked(self):
        s1 = {'tide': 'BEARISH', 'impulse_signal': 'bearish'}
        s2 = {'signal': 'BUY', 'impulse_signal': 'bullish'}
        result = validate_full_analysis(s1, s2)
        assert not result.is_valid
        assert len(result.blocks) > 0


class TestTripleScreenWithValidation:
    """Integration tests: TripleScreen now includes validation."""

    def test_bullish_setup_passes_validation(self):
        ts = TripleScreenAnalysis()
        result = ts.analyze(
            screen1_data={
                'macd_histogram_slope': 0.5,
                'impulse_signal': 'bullish',
                'ema_trend': 'RISING',
            },
            screen2_data={
                'force_index_2': -500,
                'elder_ray_bear': -2.5,
                'elder_ray_bull': 5.0,
                'elder_ray_bear_trend': 'RISING',
                'elder_ray_bull_trend': 'RISING',
                'impulse_signal': 'bullish',
            },
        )
        assert 'validation' in result
        assert result['validation']['is_valid'] is True
        assert result['recommendation']['action'] == 'BUY'

    def test_red_impulse_blocks_buy(self):
        """Screen 1 RED impulse should block BUY recommendation."""
        ts = TripleScreenAnalysis()
        result = ts.analyze(
            screen1_data={
                'macd_histogram_slope': -0.5,
                'impulse_signal': 'bearish',
                'ema_trend': 'FALLING',
            },
            screen2_data={
                'force_index_2': -500,
                'elder_ray_bear': -2.5,
                'elder_ray_bull': 5.0,
                'elder_ray_bear_trend': 'RISING',
                'elder_ray_bull_trend': 'RISING',
                'impulse_signal': 'bullish',
            },
        )
        assert 'validation' in result
        # The recommendation should be WAIT due to validation blocks
        # (tide is BEARISH, signal would be SELL from oscillator or blocked)
        action = result['recommendation']['action']
        assert action in ('WAIT', 'SELL')

    def test_validation_result_structure(self):
        ts = TripleScreenAnalysis()
        result = ts.analyze(
            screen1_data={
                'macd_histogram_slope': 0,
                'impulse_signal': 'neutral',
                'ema_trend': 'SIDEWAYS',
            },
            screen2_data={
                'force_index_2': 0,
                'impulse_signal': 'neutral',
            },
        )
        assert 'validation' in result
        v = result['validation']
        assert 'is_valid' in v
        assert 'warnings' in v
        assert 'blocks' in v
        assert isinstance(v['warnings'], list)
        assert isinstance(v['blocks'], list)

    def test_conflicting_impulse_detected(self):
        """Conflicting impulses across screens should produce warnings."""
        ts = TripleScreenAnalysis()
        result = ts.analyze(
            screen1_data={
                'macd_histogram_slope': 0.5,
                'impulse_signal': 'bullish',
                'ema_trend': 'RISING',
            },
            screen2_data={
                'force_index_2': 500,
                'elder_ray_bear': -2.5,
                'elder_ray_bull': 5.0,
                'elder_ray_bear_trend': 'FALLING',
                'elder_ray_bull_trend': 'FALLING',
                'impulse_signal': 'bearish',
            },
        )
        v = result['validation']
        # Should have warnings or blocks about conflicting impulse
        has_conflict_msg = (
            any('CONFLICT' in w or 'conflict' in w.lower() for w in v['warnings']) or
            any('BLOCKED' in b for b in v['blocks'])
        )
        assert has_conflict_msg, f"Expected conflict warning/block, got: {v}"
