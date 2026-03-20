"""IndicatorEngine — programmatic wrapper for all 10 Elder indicators.

Mirrors the computation logic in api/indicators.py but designed for
non-HTTP pipeline use (called directly from AssetSession).
"""

import numpy as np
import pandas as pd
from loguru import logger

try:
    from app.indicators.timeframe_config import should_compute_indicator
except ImportError:
    from backend.app.indicators.timeframe_config import should_compute_indicator


def _to_list(arr, n: int, decimals: int = 2, is_string: bool = False):
    """Convert indicator array to padded list with None for NaN."""
    if is_string:
        vals = list(arr)
        pad = n - len(vals)
        return [None] * pad + vals

    pad = n - len(arr)
    result = [None] * pad
    for v in arr:
        if np.isnan(v):
            result.append(None)
        else:
            result.append(round(float(v), decimals))
    return result


class IndicatorEngine:
    """Compute all Elder indicators on a candle DataFrame."""

    def __init__(self, symbol: str = "UNKNOWN", interval: str = "1d"):
        self.symbol = symbol
        self.interval = interval
        self._cache_key: str = ""  # hash of last candle count + last close
        self._cache_result: dict = {}

    def _ensure_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure DataFrame has 'datetime' column."""
        if df is None or df.empty:
            return pd.DataFrame()
        if "timestamp" in df.columns and "datetime" not in df.columns:
            df = df.rename(columns={"timestamp": "datetime"})
        if "datetime" not in df.columns:
            if df.index.name in ("datetime", "timestamp"):
                df = df.reset_index()
            else:
                df["datetime"] = pd.date_range(
                    end=pd.Timestamp.now(), periods=len(df), freq="D"
                )
        return df

    def compute_all(self, df: pd.DataFrame) -> dict:
        """Compute all indicators. Returns dict of arrays keyed by indicator name."""
        return self.compute_for_screen(df, screen=None)

    def compute_for_screen(self, df: pd.DataFrame, screen: int = None) -> dict:
        """Compute indicators relevant to a specific screen (or all if None).

        Args:
            df: DataFrame with datetime, open, high, low, close, volume columns.
            screen: 1, 2, 3 to filter, or None for all.

        Returns:
            Dict mapping indicator keys to lists of values.
        """
        df = self._ensure_columns(df)
        if df.empty:
            return {}

        n = len(df)

        # Cache: skip full recalc if data hasn't changed
        last_close = float(df.iloc[-1].get("close", 0)) if n > 0 else 0
        cache_key = f"{n}:{last_close}:{screen}"
        if cache_key == self._cache_key and self._cache_result:
            return self._cache_result
        sym = self.symbol
        iv = self.interval
        result = {}

        # Timestamps
        result["timestamps"] = []
        for ts in df["datetime"]:
            if hasattr(ts, "isoformat"):
                result["timestamps"].append(ts.isoformat())
            else:
                result["timestamps"].append(str(ts))

        # EMA-13
        if should_compute_indicator("ema13", screen):
            try:
                from app.indicators.ema import EMAEnhanced
                ema = EMAEnhanced(sym, iv, {"period": 13, "source": "close", "ma_type": "None"})
                out = ema.calculate(df)
                result["ema13"] = _to_list(out["ema"].values, n)
            except Exception as e:
                logger.warning("IndicatorEngine EMA-13: {}", e)
                result["ema13"] = [None] * n
        else:
            result["ema13"] = [None] * n

        # EMA-22
        if should_compute_indicator("ema22", screen):
            try:
                from app.indicators.ema import EMAEnhanced
                ema = EMAEnhanced(sym, iv, {"period": 22, "source": "close", "ma_type": "None"})
                out = ema.calculate(df)
                result["ema22"] = _to_list(out["ema"].values, n)
            except Exception as e:
                logger.warning("IndicatorEngine EMA-22: {}", e)
                result["ema22"] = [None] * n
        else:
            result["ema22"] = [None] * n

        # MACD
        if should_compute_indicator("macd", screen):
            try:
                from app.indicators.macd import MACDEnhanced
                macd = MACDEnhanced(sym, iv, {
                    "fast_length": 12, "slow_length": 26, "signal_length": 9,
                    "source": "close", "oscillator_ma_type": "EMA", "signal_ma_type": "EMA",
                })
                out = macd.calculate(df)
                result["macd_line"] = _to_list(out["macd_line"].values, n)
                result["macd_signal"] = _to_list(out["signal_line"].values, n)
                result["macd_histogram"] = _to_list(out["histogram"].values, n)
            except Exception as e:
                logger.warning("IndicatorEngine MACD: {}", e)
                result["macd_line"] = [None] * n
                result["macd_signal"] = [None] * n
                result["macd_histogram"] = [None] * n
        else:
            result["macd_line"] = [None] * n
            result["macd_signal"] = [None] * n
            result["macd_histogram"] = [None] * n

        # Force Index (13)
        if should_compute_indicator("force_index_13", screen):
            try:
                from app.indicators.force_index import ForceIndexEnhanced
                fi = ForceIndexEnhanced(sym, iv, {"length": 13, "source": "close"})
                out = fi.calculate(df)
                result["force_index"] = _to_list(out["efi"].values, n)
            except Exception as e:
                logger.warning("IndicatorEngine FI-13: {}", e)
                result["force_index"] = [None] * n
        else:
            result["force_index"] = [None] * n

        # Force Index (2)
        if should_compute_indicator("force_index_2", screen):
            try:
                from app.indicators.force_index import ForceIndexEnhanced
                fi = ForceIndexEnhanced(sym, iv, {"length": 2, "source": "close"})
                out = fi.calculate(df)
                result["force_index_2"] = _to_list(out["efi"].values, n)
            except Exception as e:
                logger.warning("IndicatorEngine FI-2: {}", e)
                result["force_index_2"] = [None] * n
        else:
            result["force_index_2"] = [None] * n

        # Impulse
        if should_compute_indicator("impulse", screen):
            try:
                from app.indicators.impulse import ElderImpulseEnhanced
                imp = ElderImpulseEnhanced(sym, iv, {
                    "macd_fast_length": 12, "macd_slow_length": 26,
                    "macd_signal_length": 9, "ema_length": 13, "source": "close",
                    "bullish_color": "green", "bearish_color": "red", "neutral_color": "blue",
                })
                out = imp.calculate(df)
                result["impulse_color"] = _to_list(out["impulse_color"].tolist(), n, is_string=True)
                result["impulse_signal"] = _to_list(out["impulse_signal"].tolist(), n, is_string=True)
            except Exception as e:
                logger.warning("IndicatorEngine Impulse: {}", e)
                result["impulse_color"] = [None] * n
                result["impulse_signal"] = [None] * n
        else:
            result["impulse_color"] = [None] * n
            result["impulse_signal"] = [None] * n

        # SafeZone
        if should_compute_indicator("safezone", screen):
            try:
                from app.indicators.safezone import SafeZoneV2
                sz = SafeZoneV2(sym, iv, {
                    "lookback_length": 22, "coefficient": 2.0, "progressive_mode": True,
                })
                out = sz.calculate(df)
                result["safezone_long"] = _to_list(out["longvs"].values, n)
                result["safezone_short"] = _to_list(out["shortvs"].values, n)
            except Exception as e:
                logger.warning("IndicatorEngine SafeZone: {}", e)
                result["safezone_long"] = [None] * n
                result["safezone_short"] = [None] * n
        else:
            result["safezone_long"] = [None] * n
            result["safezone_short"] = [None] * n

        # Elder Ray
        if should_compute_indicator("elder_ray", screen):
            try:
                from app.indicators.elder_ray import ElderRay
                er = ElderRay(sym, iv, {"period": 13})
                out = er.calculate(df)
                result["elder_ray_bull"] = _to_list(out["bull_power"].values, n)
                result["elder_ray_bear"] = _to_list(out["bear_power"].values, n)
            except Exception as e:
                logger.warning("IndicatorEngine ElderRay: {}", e)
                result["elder_ray_bull"] = [None] * n
                result["elder_ray_bear"] = [None] * n
        else:
            result["elder_ray_bull"] = [None] * n
            result["elder_ray_bear"] = [None] * n

        # Value Zone
        if should_compute_indicator("value_zone", screen):
            try:
                from app.indicators.value_zone import ValueZone
                vz = ValueZone(sym, iv, {"fast_period": 13, "slow_period": 26})
                out = vz.calculate(df)
                result["value_zone_fast"] = _to_list(out["fast_ema"].values, n)
                result["value_zone_slow"] = _to_list(out["slow_ema"].values, n)
            except Exception as e:
                logger.warning("IndicatorEngine ValueZone: {}", e)
                result["value_zone_fast"] = [None] * n
                result["value_zone_slow"] = [None] * n
        else:
            result["value_zone_fast"] = [None] * n
            result["value_zone_slow"] = [None] * n

        # AutoEnvelope
        if should_compute_indicator("auto_envelope", screen):
            try:
                from app.indicators.auto_envelope import AutoEnvelope
                ae = AutoEnvelope(sym, iv, {"period": 22, "multiplier": 2.7, "lookback": 100})
                out = ae.calculate(df)
                result["auto_envelope_upper"] = _to_list(out["upper"].values, n)
                result["auto_envelope_lower"] = _to_list(out["lower"].values, n)
                result["auto_envelope_ema"] = _to_list(out["ema"].values, n)
            except Exception as e:
                logger.warning("IndicatorEngine AutoEnvelope: {}", e)
                result["auto_envelope_upper"] = [None] * n
                result["auto_envelope_lower"] = [None] * n
                result["auto_envelope_ema"] = [None] * n
        else:
            result["auto_envelope_upper"] = [None] * n
            result["auto_envelope_lower"] = [None] * n
            result["auto_envelope_ema"] = [None] * n

        # Elder Thermometer
        if should_compute_indicator("elder_thermometer", screen):
            try:
                from app.indicators.elder_thermometer import ElderThermometer
                et = ElderThermometer(sym, iv, {"period": 22})
                out = et.calculate(df)
                result["thermometer_raw"] = _to_list(out["raw"].values, n, decimals=4)
                result["thermometer_smoothed"] = _to_list(out["smoothed"].values, n, decimals=4)
            except Exception as e:
                logger.warning("IndicatorEngine Thermometer: {}", e)
                result["thermometer_raw"] = [None] * n
                result["thermometer_smoothed"] = [None] * n
        else:
            result["thermometer_raw"] = [None] * n
            result["thermometer_smoothed"] = [None] * n

        # MACD Divergence
        if should_compute_indicator("macd_divergence", screen):
            try:
                from app.indicators.macd_divergence import MACDDivergence
                md = MACDDivergence(sym, iv, {
                    "fast_length": 12, "slow_length": 26, "signal_length": 9,
                })
                out = md.calculate(df)
                result["macd_divergence_signal"] = _to_list(out["divergence_signal"].values, n)
            except Exception as e:
                logger.warning("IndicatorEngine MACDDiv: {}", e)
                result["macd_divergence_signal"] = [None] * n
        else:
            result["macd_divergence_signal"] = [None] * n

        # Cache result
        self._cache_key = cache_key
        self._cache_result = result
        return result
