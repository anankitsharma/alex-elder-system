"""
Tests for per-timeframe indicator configuration.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.app.indicators.timeframe_config import (
    get_asset_class,
    get_indicators_for_screen,
    get_timeframe_for_screen,
    should_compute_indicator,
    SCREEN_INDICATOR_CONFIG,
    ALL_INDICATORS,
)


class TestGetAssetClass:
    def test_equity_nse(self):
        assert get_asset_class('RELIANCE', 'NSE') == 'EQUITY'

    def test_equity_bse(self):
        assert get_asset_class('TCS', 'BSE') == 'EQUITY'

    def test_index_fo(self):
        assert get_asset_class('NIFTY', 'NFO') == 'INDEX_FO'

    def test_banknifty(self):
        assert get_asset_class('BANKNIFTY', 'NFO') == 'INDEX_FO'

    def test_commodity_mcx(self):
        assert get_asset_class('GOLDM', 'MCX') == 'COMMODITY'

    def test_commodity_by_exchange(self):
        assert get_asset_class('UNKNOWN', 'MCX') == 'COMMODITY'

    def test_default_unknown(self):
        assert get_asset_class('UNKNOWN', 'UNKNOWN') == 'DEFAULT'


class TestGetIndicatorsForScreen:
    def test_screen1_has_ema_macd_impulse(self):
        indicators = get_indicators_for_screen(1)
        assert 'ema13' in indicators
        assert 'macd' in indicators
        assert 'impulse' in indicators

    def test_screen2_has_all_oscillators(self):
        indicators = get_indicators_for_screen(2)
        assert 'force_index_2' in indicators
        assert 'elder_ray' in indicators
        assert 'safezone' in indicators
        assert 'value_zone' in indicators

    def test_screen3_has_precision_indicators(self):
        indicators = get_indicators_for_screen(3)
        assert 'safezone' in indicators
        assert 'force_index_2' in indicators
        assert 'impulse' in indicators

    def test_invalid_screen_returns_all(self):
        indicators = get_indicators_for_screen(99)
        assert indicators == ALL_INDICATORS


class TestGetTimeframeForScreen:
    def test_equity_screen1_weekly(self):
        assert get_timeframe_for_screen('RELIANCE', 1, 'NSE') == '1w'

    def test_equity_screen2_daily(self):
        assert get_timeframe_for_screen('RELIANCE', 2, 'NSE') == '1d'

    def test_equity_screen3_hourly(self):
        assert get_timeframe_for_screen('RELIANCE', 3, 'NSE') == '1h'

    def test_index_fo_screen1_daily(self):
        assert get_timeframe_for_screen('NIFTY', 1, 'NFO') == '1d'

    def test_index_fo_screen2_hourly(self):
        assert get_timeframe_for_screen('NIFTY', 2, 'NFO') == '1h'

    def test_commodity_screen3_15m(self):
        assert get_timeframe_for_screen('GOLDM', 3, 'MCX') == '15m'


class TestShouldComputeIndicator:
    def test_none_screen_computes_all(self):
        assert should_compute_indicator('ema13', None) is True
        assert should_compute_indicator('auto_envelope', None) is True

    def test_screen1_includes_macd(self):
        assert should_compute_indicator('macd', 1) is True

    def test_screen1_excludes_elder_ray(self):
        assert should_compute_indicator('elder_ray', 1) is False

    def test_screen2_includes_elder_ray(self):
        assert should_compute_indicator('elder_ray', 2) is True

    def test_screen3_excludes_auto_envelope(self):
        assert should_compute_indicator('auto_envelope', 3) is False
