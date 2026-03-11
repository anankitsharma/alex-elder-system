"""
Tests for the Multi-Asset Screener.
"""

import pytest
import pandas as pd
import numpy as np

from backend.app.scanner.screener import AssetScreener, ScreenResult, ScreenFilter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 200, trend: str = "up") -> pd.DataFrame:
    """Generate OHLCV data with a directional trend."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=n, freq="15min")

    if trend == "up":
        close = 100 + np.linspace(0, 30, n) + rng.standard_normal(n) * 0.5
    elif trend == "down":
        close = 130 - np.linspace(0, 30, n) + rng.standard_normal(n) * 0.5
    else:
        close = 100 + rng.standard_normal(n).cumsum() * 0.3

    high = close + rng.uniform(0.3, 1.5, n)
    low = close - rng.uniform(0.3, 1.5, n)
    opn = close + rng.uniform(-0.8, 0.8, n)
    high = np.maximum(high, np.maximum(opn, close))
    low = np.minimum(low, np.minimum(opn, close))
    volume = rng.integers(500, 50000, n)

    return pd.DataFrame({
        "datetime": dates, "open": opn, "high": high,
        "low": low, "close": close, "volume": volume,
    })


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

class TestAssetScreener:

    def test_scan_single_symbol(self):
        screener = AssetScreener()
        data = {"TEST": _make_ohlcv(200, "up")}
        results = screener.scan(data, "15m")
        assert len(results) == 1
        r = results[0]
        assert r.symbol == "TEST"
        assert r.timeframe == "15m"
        assert r.impulse_signal in ("bullish", "bearish", "neutral")
        assert r.impulse_color in ("green", "red", "blue")
        assert 0 <= r.score <= 100

    def test_scan_multiple_symbols(self):
        screener = AssetScreener()
        data = {
            "A": _make_ohlcv(200, "up"),
            "B": _make_ohlcv(200, "down"),
            "C": _make_ohlcv(200, "sideways"),
        }
        results = screener.scan(data, "15m")
        assert len(results) == 3
        symbols = {r.symbol for r in results}
        assert symbols == {"A", "B", "C"}

    def test_scan_sorted_by_score(self):
        screener = AssetScreener()
        data = {
            "A": _make_ohlcv(200, "up"),
            "B": _make_ohlcv(200, "down"),
        }
        results = screener.scan(data, "15m")
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_scan_skips_short_data(self):
        screener = AssetScreener()
        data = {"SHORT": _make_ohlcv(10)}
        results = screener.scan(data, "15m")
        assert len(results) == 0

    def test_scan_skips_empty_data(self):
        screener = AssetScreener()
        data = {"EMPTY": pd.DataFrame()}
        results = screener.scan(data, "15m")
        assert len(results) == 0

    def test_result_has_indicator_values(self):
        screener = AssetScreener()
        data = {"TEST": _make_ohlcv(200, "up")}
        results = screener.scan(data, "15m")
        r = results[0]
        assert r.ema_value is not None
        assert r.last_close is not None
        assert r.avg_volume is not None
        assert r.fi_value is not None

    def test_result_has_safezone(self):
        screener = AssetScreener()
        data = {"TEST": _make_ohlcv(200, "up")}
        results = screener.scan(data, "15m")
        r = results[0]
        # SafeZone should be present with sufficient data
        assert r.safezone_long is not None or r.safezone_short is not None

    def test_result_direction(self):
        screener = AssetScreener()
        data = {"TEST": _make_ohlcv(200, "up")}
        results = screener.scan(data, "15m")
        r = results[0]
        if r.impulse_signal == "bullish":
            assert r.direction == "LONG"
        elif r.impulse_signal == "bearish":
            assert r.direction == "SHORT"
        else:
            assert r.direction is None

    def test_is_bullish_bearish_properties(self):
        r = ScreenResult("A", "15m", "bullish", "green", 80)
        assert r.is_bullish is True
        assert r.is_bearish is False

        r2 = ScreenResult("B", "15m", "bearish", "red", 80)
        assert r2.is_bullish is False
        assert r2.is_bearish is True


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

class TestScreenFilter:

    def _make_results(self) -> list:
        return [
            ScreenResult("A", "15m", "bullish", "green", 85, "LONG", fi_value=100, avg_volume=5000),
            ScreenResult("B", "15m", "bearish", "red", 70, "SHORT", fi_value=-50, avg_volume=3000),
            ScreenResult("C", "15m", "neutral", "blue", 20, None, fi_value=10, avg_volume=1000),
            ScreenResult("D", "15m", "bullish", "green", 60, "LONG", fi_value=200, avg_volume=8000),
        ]

    def test_filter_by_impulse_color(self):
        results = self._make_results()
        filtered = AssetScreener.filter_results(results, ScreenFilter(impulse_colors=["green"]))
        assert len(filtered) == 2
        assert all(r.impulse_color == "green" for r in filtered)

    def test_filter_by_min_score(self):
        results = self._make_results()
        filtered = AssetScreener.filter_results(results, ScreenFilter(min_score=60))
        assert len(filtered) == 3
        assert all(r.score >= 60 for r in filtered)

    def test_filter_by_direction(self):
        results = self._make_results()
        filtered = AssetScreener.filter_results(results, ScreenFilter(direction="SHORT"))
        assert len(filtered) == 1
        assert filtered[0].symbol == "B"

    def test_filter_fi_above_zero(self):
        results = self._make_results()
        filtered = AssetScreener.filter_results(results, ScreenFilter(fi_above_zero=True))
        assert len(filtered) == 3  # A, C, D have fi > 0

    def test_filter_fi_below_zero(self):
        results = self._make_results()
        filtered = AssetScreener.filter_results(results, ScreenFilter(fi_above_zero=False))
        assert len(filtered) == 1
        assert filtered[0].symbol == "B"

    def test_filter_min_volume(self):
        results = self._make_results()
        filtered = AssetScreener.filter_results(results, ScreenFilter(min_volume=4000))
        assert len(filtered) == 2
        assert {r.symbol for r in filtered} == {"A", "D"}

    def test_filter_combined(self):
        results = self._make_results()
        filtered = AssetScreener.filter_results(results, ScreenFilter(
            impulse_colors=["green"], min_score=70, direction="LONG",
        ))
        assert len(filtered) == 1
        assert filtered[0].symbol == "A"

    def test_top_n(self):
        results = self._make_results()
        top = AssetScreener.top_n(results, n=2)
        assert len(top) == 2
        assert top[0].score >= top[1].score
