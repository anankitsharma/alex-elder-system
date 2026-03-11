"""
Tests for Triple Screen Trading System.
"""

import pytest
from backend.app.strategy.triple_screen import TripleScreenAnalysis


class TestTripleScreen:
    def _make(self):
        return TripleScreenAnalysis()

    # ------------------------------------------------------------------
    # Screen 1 — Trend
    # ------------------------------------------------------------------

    def test_screen1_bullish_tide(self):
        ts = self._make()
        result = ts.analyze(
            screen1_data={"macd_histogram_slope": 0.5, "impulse_signal": "bullish", "ema_trend": "UP"},
            screen2_data={"force_index_2": -100, "impulse_signal": "bullish"},
        )
        assert result["screen1"]["tide"] == "BULLISH"
        assert result["screen1"]["impulse_confirms"] is True

    def test_screen1_bearish_tide(self):
        ts = self._make()
        result = ts.analyze(
            screen1_data={"macd_histogram_slope": -0.3, "impulse_signal": "bearish"},
            screen2_data={"force_index_2": 100, "impulse_signal": "bearish"},
        )
        assert result["screen1"]["tide"] == "BEARISH"

    def test_screen1_neutral_tide(self):
        ts = self._make()
        result = ts.analyze(
            screen1_data={"macd_histogram_slope": 0},
            screen2_data={},
        )
        assert result["screen1"]["tide"] == "NEUTRAL"
        assert result["recommendation"]["action"] == "WAIT"

    # ------------------------------------------------------------------
    # Screen 2 — Oscillator
    # ------------------------------------------------------------------

    def test_screen2_buy_signal(self):
        ts = self._make()
        result = ts.analyze(
            screen1_data={"macd_histogram_slope": 0.5, "impulse_signal": "bullish"},
            screen2_data={"force_index_2": -50, "impulse_signal": "bullish"},
        )
        assert result["screen2"]["signal"] == "BUY"

    def test_screen2_buy_on_bear_power(self):
        ts = self._make()
        result = ts.analyze(
            screen1_data={"macd_histogram_slope": 0.5, "impulse_signal": "bullish"},
            screen2_data={
                "force_index_2": 10,  # Not negative
                "elder_ray_bear": -2.0,
                "elder_ray_bear_trend": "RISING",
            },
        )
        assert result["screen2"]["signal"] == "BUY"

    def test_screen2_sell_signal(self):
        ts = self._make()
        result = ts.analyze(
            screen1_data={"macd_histogram_slope": -0.3, "impulse_signal": "bearish"},
            screen2_data={"force_index_2": 50, "impulse_signal": "bearish"},
        )
        assert result["screen2"]["signal"] == "SELL"

    def test_screen2_sell_on_bull_power(self):
        ts = self._make()
        result = ts.analyze(
            screen1_data={"macd_histogram_slope": -0.3, "impulse_signal": "bearish"},
            screen2_data={
                "force_index_2": -10,  # Not positive
                "elder_ray_bull": 2.0,
                "elder_ray_bull_trend": "FALLING",
            },
        )
        assert result["screen2"]["signal"] == "SELL"

    def test_screen2_no_signal_wrong_conditions(self):
        ts = self._make()
        result = ts.analyze(
            screen1_data={"macd_histogram_slope": 0.5},
            screen2_data={"force_index_2": 100},  # FI positive in bullish tide
        )
        assert result["screen2"]["signal"] == "NONE"

    # ------------------------------------------------------------------
    # Screen 3 — Entry
    # ------------------------------------------------------------------

    def test_screen3_buy_stop(self):
        ts = self._make()
        result = ts.analyze(
            screen1_data={"macd_histogram_slope": 0.5, "impulse_signal": "bullish"},
            screen2_data={"force_index_2": -50},
            screen3_data={"last_high": 105, "last_low": 95, "safezone_long": 96},
        )
        assert result["screen3"]["entry_type"] == "BUY_STOP"
        assert result["screen3"]["entry_price"] == 105
        assert result["screen3"]["stop_price"] == 96

    def test_screen3_sell_stop(self):
        ts = self._make()
        result = ts.analyze(
            screen1_data={"macd_histogram_slope": -0.3, "impulse_signal": "bearish"},
            screen2_data={"force_index_2": 50},
            screen3_data={"last_high": 105, "last_low": 95, "safezone_short": 106},
        )
        assert result["screen3"]["entry_type"] == "SELL_STOP"
        assert result["screen3"]["entry_price"] == 95
        assert result["screen3"]["stop_price"] == 106

    # ------------------------------------------------------------------
    # Recommendation
    # ------------------------------------------------------------------

    def test_recommendation_buy(self):
        ts = self._make()
        result = ts.analyze(
            screen1_data={"macd_histogram_slope": 0.5, "impulse_signal": "bullish"},
            screen2_data={"force_index_2": -50, "impulse_signal": "bullish"},
        )
        assert result["recommendation"]["action"] == "BUY"
        assert result["recommendation"]["confidence"] > 0

    def test_recommendation_sell(self):
        ts = self._make()
        result = ts.analyze(
            screen1_data={"macd_histogram_slope": -0.3, "impulse_signal": "bearish"},
            screen2_data={"force_index_2": 50, "impulse_signal": "bearish"},
        )
        assert result["recommendation"]["action"] == "SELL"

    def test_recommendation_wait_neutral(self):
        ts = self._make()
        result = ts.analyze(
            screen1_data={"macd_histogram_slope": 0},
            screen2_data={},
        )
        assert result["recommendation"]["action"] == "WAIT"

    def test_recommendation_wait_no_wave(self):
        ts = self._make()
        result = ts.analyze(
            screen1_data={"macd_histogram_slope": 0.5},
            screen2_data={"force_index_2": 100},  # Not ready
        )
        assert result["recommendation"]["action"] == "WAIT"

    def test_confidence_increases_with_confirmations(self):
        # Minimal
        ts = self._make()
        r1 = ts.analyze(
            screen1_data={"macd_histogram_slope": 0.5},
            screen2_data={"force_index_2": -50},
        )
        # Full confirmation
        r2 = ts.analyze(
            screen1_data={"macd_histogram_slope": 0.5, "impulse_signal": "bullish"},
            screen2_data={
                "force_index_2": -50,
                "elder_ray_bear": -1.0,
                "elder_ray_bear_trend": "RISING",
                "impulse_signal": "bullish",
            },
        )
        assert r2["recommendation"]["confidence"] > r1["recommendation"]["confidence"]

    # ------------------------------------------------------------------
    # Trade Grading
    # ------------------------------------------------------------------

    def test_grade_a_trade(self):
        ts = self._make()
        result = ts.analyze(
            screen1_data={"macd_histogram_slope": 0.5, "impulse_signal": "bullish"},
            screen2_data={
                "force_index_2": -50,
                "impulse_signal": "bullish",
                "value_zone_position": 0,  # In zone
            },
        )
        assert result["grade"] == "A"

    def test_grade_b_trade(self):
        ts = self._make()
        result = ts.analyze(
            screen1_data={"macd_histogram_slope": 0.5, "impulse_signal": "bullish"},
            screen2_data={
                "force_index_2": -50,
                "impulse_signal": "bullish",
                "value_zone_position": 1,  # Above zone
            },
        )
        assert result["grade"] == "B"

    def test_grade_c_trade(self):
        ts = self._make()
        result = ts.analyze(
            screen1_data={"macd_histogram_slope": 0.5},  # No impulse confirm
            screen2_data={"force_index_2": -50, "impulse_signal": "neutral"},
        )
        assert result["grade"] == "C"

    def test_grade_d_trade(self):
        ts = self._make()
        result = ts.analyze(
            screen1_data={"macd_histogram_slope": 0.5},
            screen2_data={"force_index_2": 100},  # No signal
        )
        assert result["grade"] == "D"

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_empty_screen2(self):
        ts = self._make()
        result = ts.analyze(
            screen1_data={"macd_histogram_slope": 0.5},
            screen2_data={},
        )
        assert result["recommendation"]["action"] == "WAIT"

    def test_no_screen3(self):
        ts = self._make()
        result = ts.analyze(
            screen1_data={"macd_histogram_slope": 0.5, "impulse_signal": "bullish"},
            screen2_data={"force_index_2": -50},
        )
        assert result["screen3"]["entry_type"] == "MARKET"

    def test_full_analysis_structure(self):
        ts = self._make()
        result = ts.analyze(
            screen1_data={"macd_histogram_slope": 0.5, "impulse_signal": "bullish"},
            screen2_data={"force_index_2": -50, "impulse_signal": "bullish"},
            screen3_data={"last_high": 105, "last_low": 95, "safezone_long": 96},
        )
        assert "screen1" in result
        assert "screen2" in result
        assert "screen3" in result
        assert "recommendation" in result
        assert "grade" in result
