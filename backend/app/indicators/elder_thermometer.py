"""
Elder Thermometer — Volatility Measurement

From Dr. Alexander Elder's "Trading for a Living" (Chapter 11) and
"Come Into My Trading Room".

Measures the "temperature" of the market by tracking the greater of:
- Current high - previous high (upside reach)
- Previous low - current low (downside reach)

Then smoothed with EMA. Elder's classic period is 13 bars; some implementations
use 22 bars for a smoother signal. This implementation defaults to 22 but
provides CLASSIC_PERIOD = 13 for Elder's original specification.

Trading Rules:
- High readings = high volatility, often near climax/reversal
- Low readings = low volatility, consolidation, possible breakout ahead
- Use EMA of thermometer to identify normal vs abnormal volatility
- Spike above 2x average = possible exhaustion
- Elder recommends period=13 for the classic thermometer
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from loguru import logger
from .base import BaseIndicator


# Elder's recommended classic period (from "Trading for a Living")
CLASSIC_PERIOD = 13


class ElderThermometer(BaseIndicator):
    """
    Elder Thermometer — Volatility indicator.

    Formula:
    thermo[i] = max(high[i] - high[i-1], low[i-1] - low[i])
    thermo[i] = max(thermo[i], 0)  (floor at zero)
    smoothed = EMA(thermo, period)

    Features:
    - Raw thermometer (per-bar volatility)
    - Smoothed thermometer (EMA, default 22; Elder's classic = 13)
    - Spike detection (above 2x average)
    - Volatility regime classification

    Note: Default period is 22 for backward compatibility. Elder's original
    specification in "Trading for a Living" uses period=13 (CLASSIC_PERIOD).
    """

    def __init__(self, symbol: str, timeframe: str, config: Dict[str, Any]):
        self.period = config.get('period', 22)
        self.spike_multiplier = config.get('spike_multiplier', 2.0)

        super().__init__(symbol, timeframe, config)

        self.raw_thermo = None
        self.smoothed_thermo = None

    def validate_config(self) -> bool:
        if not isinstance(self.period, int) or self.period <= 0:
            logger.error(f"Invalid period: {self.period}")
            return False
        if not isinstance(self.spike_multiplier, (int, float)) or self.spike_multiplier <= 0:
            logger.error(f"Invalid spike_multiplier: {self.spike_multiplier}")
            return False
        return True

    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate Elder Thermometer."""
        if not self.validate_data(data):
            raise ValueError("Invalid data for Elder Thermometer calculation")

        if len(data) < self.period + 2:
            raise ValueError(f"Insufficient data: need at least {self.period + 2} bars")

        try:
            high = data['high'].values
            low = data['low'].values

            # Raw thermometer: max(high - prev_high, prev_low - low), floored at 0
            raw = np.full(len(data), np.nan)
            for i in range(1, len(data)):
                upside_reach = high[i] - high[i - 1]
                downside_reach = low[i - 1] - low[i]
                raw[i] = max(upside_reach, downside_reach, 0.0)

            # EMA smoothing of raw thermometer
            smoothed = self._calculate_ema_from_index(raw, self.period, start_search=1)

            # Find first valid smoothed value
            valid_start = None
            for i in range(len(smoothed)):
                if not np.isnan(smoothed[i]):
                    valid_start = i
                    break

            if valid_start is None:
                raise ValueError("No valid Thermometer values calculated")

            aligned_raw = raw[valid_start:]
            aligned_smoothed = smoothed[valid_start:]
            aligned_datetime = data['datetime'].values[valid_start:]

            # Spike detection
            is_spike = aligned_raw > (aligned_smoothed * self.spike_multiplier)

            result = pd.DataFrame({
                'datetime': aligned_datetime,
                'raw': aligned_raw,
                'smoothed': aligned_smoothed,
                'is_spike': is_spike,
                'value': aligned_smoothed
            })

            self.raw_thermo = aligned_raw
            self.smoothed_thermo = aligned_smoothed
            self.values = aligned_smoothed

            self.calculation_metadata = {
                'period': self.period,
                'spike_multiplier': self.spike_multiplier,
                'data_points_used': len(data),
                'points_calculated': len(result),
                'last_raw': float(aligned_raw[-1]),
                'last_smoothed': float(aligned_smoothed[-1]),
                'is_current_spike': bool(is_spike[-1]),
            }

            logger.debug(f"Calculated Elder Thermometer with {len(result)} values")
            return result

        except Exception as e:
            logger.error(f"Error calculating Elder Thermometer: {e}")
            raise

    def _calculate_ema_from_index(self, data: np.ndarray, period: int, start_search: int = 0) -> np.ndarray:
        """Calculate EMA starting from first non-NaN value."""
        alpha = 2.0 / (period + 1)
        result = np.full(len(data), np.nan)

        # Find first valid index
        first_valid = None
        for i in range(start_search, len(data)):
            if not np.isnan(data[i]):
                first_valid = i
                break

        if first_valid is None:
            return result

        # Need 'period' valid values for initial SMA seed
        valid_count = 0
        seed_values = []
        seed_end = first_valid
        for i in range(first_valid, len(data)):
            if not np.isnan(data[i]):
                seed_values.append(data[i])
                valid_count += 1
                if valid_count == period:
                    seed_end = i
                    break

        if valid_count < period:
            return result

        result[seed_end] = np.mean(seed_values)

        for i in range(seed_end + 1, len(data)):
            if not np.isnan(data[i]):
                result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
            else:
                result[i] = result[i - 1]

        return result

    # --- Public getters ---

    def get_raw_value(self, index: Optional[int] = None) -> Optional[float]:
        if self.raw_thermo is None or len(self.raw_thermo) == 0:
            return None
        idx = index if index is not None else -1
        return float(self.raw_thermo[idx])

    def get_smoothed_value(self, index: Optional[int] = None) -> Optional[float]:
        if self.smoothed_thermo is None or len(self.smoothed_thermo) == 0:
            return None
        idx = index if index is not None else -1
        return float(self.smoothed_thermo[idx])

    def is_spike(self) -> bool:
        """Check if current bar is a volatility spike."""
        if self.raw_thermo is None or self.smoothed_thermo is None:
            return False
        return float(self.raw_thermo[-1]) > float(self.smoothed_thermo[-1]) * self.spike_multiplier

    def get_volatility_regime(self) -> str:
        """Classify current volatility regime."""
        if self.raw_thermo is None or self.smoothed_thermo is None:
            return 'UNKNOWN'
        raw = float(self.raw_thermo[-1])
        avg = float(self.smoothed_thermo[-1])
        if avg == 0:
            return 'UNKNOWN'
        ratio = raw / avg
        if ratio > self.spike_multiplier:
            return 'EXTREME'
        elif ratio > 1.2:
            return 'HIGH'
        elif ratio > 0.8:
            return 'NORMAL'
        return 'LOW'

    def get_signal_summary(self) -> Dict[str, Any]:
        if self.raw_thermo is None or self.smoothed_thermo is None:
            return {'status': 'no_data'}
        return {
            'raw': float(self.raw_thermo[-1]),
            'smoothed': float(self.smoothed_thermo[-1]),
            'is_spike': self.is_spike(),
            'regime': self.get_volatility_regime(),
        }

    def get_required_data_points(self) -> int:
        return self.period + 2
