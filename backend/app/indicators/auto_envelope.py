"""
AutoEnvelope — EMA-22 ± Standard Deviation Channel

Elder's AutoEnvelope creates a channel around EMA-22 using standard deviation
of the distance between close and EMA-22 over a lookback period.

Default: EMA-22 ± 2.7 standard deviations over 100 bars.

Trading Rules:
- Channel should contain ~95% of price action
- Sell when price touches upper envelope in downtrend
- Buy when price touches lower envelope in uptrend
- Channel width indicates volatility
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from loguru import logger
from .base import BaseIndicator


class AutoEnvelope(BaseIndicator):
    """
    AutoEnvelope — EMA-22 ± SD channel.

    Formula:
    - Center = EMA(close, period)
    - Deviation = StdDev(close - EMA, lookback) * multiplier
    - Upper = Center + Deviation
    - Lower = Center - Deviation

    Features:
    - Configurable EMA period (default 22)
    - Configurable SD multiplier (default 2.7)
    - Configurable lookback for SD calculation (default 100)
    - Channel width as volatility measure
    - Overbought/oversold detection at channel extremes
    """

    def __init__(self, symbol: str, timeframe: str, config: Dict[str, Any]):
        self.period = config.get('period', 22)
        self.multiplier = config.get('multiplier', 2.7)
        self.lookback = config.get('lookback', 100)
        self.source = config.get('source', 'close')
        self.ddof = config.get('ddof', 0)  # Population SD (Elder's 2.7σ channel)

        super().__init__(symbol, timeframe, config)

        self.ema_values = None
        self.upper_envelope = None
        self.lower_envelope = None
        self.channel_width = None

    def validate_config(self) -> bool:
        if not isinstance(self.period, int) or self.period <= 0:
            logger.error(f"Invalid period: {self.period}")
            return False
        if not isinstance(self.lookback, int) or self.lookback <= 0:
            logger.error(f"Invalid lookback: {self.lookback}")
            return False
        if not isinstance(self.multiplier, (int, float)) or self.multiplier <= 0:
            logger.error(f"Invalid multiplier: {self.multiplier}")
            return False
        return True

    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate AutoEnvelope."""
        if not self.validate_data(data):
            raise ValueError("Invalid data for AutoEnvelope calculation")

        min_required = max(self.period, self.lookback) + 1
        if len(data) < min_required:
            raise ValueError(f"Insufficient data: need at least {min_required} bars")

        try:
            source_data = data[self.source].values if self.source in data.columns else data['close'].values

            # Calculate EMA
            ema = self._calculate_ema(source_data, self.period)

            # Start from where EMA is valid
            start_idx = self.period - 1

            # Calculate deviation of close from EMA
            deviation = source_data - ema
            deviation[:start_idx] = np.nan

            # Rolling standard deviation of the deviation
            rolling_sd = np.full(len(data), np.nan)
            for i in range(start_idx + self.lookback - 1, len(data)):
                window = deviation[i - self.lookback + 1:i + 1]
                valid = window[~np.isnan(window)]
                if len(valid) > 1:
                    rolling_sd[i] = np.std(valid, ddof=self.ddof)

            # Find first valid SD
            valid_start = None
            for i in range(len(rolling_sd)):
                if not np.isnan(rolling_sd[i]):
                    valid_start = i
                    break

            if valid_start is None:
                raise ValueError("No valid AutoEnvelope values calculated")

            # Align all arrays
            aligned_ema = ema[valid_start:]
            aligned_sd = rolling_sd[valid_start:]
            aligned_datetime = data['datetime'].values[valid_start:]
            aligned_close = source_data[valid_start:]

            upper = aligned_ema + aligned_sd * self.multiplier
            lower = aligned_ema - aligned_sd * self.multiplier
            width = upper - lower

            # Percent position within channel (0 = lower, 1 = upper)
            pct_position = np.where(
                width > 0,
                (aligned_close - lower) / width,
                0.5
            )

            result = pd.DataFrame({
                'datetime': aligned_datetime,
                'ema': aligned_ema,
                'upper': upper,
                'lower': lower,
                'width': width,
                'pct_position': pct_position,
                'value': aligned_ema
            })

            self.ema_values = aligned_ema
            self.upper_envelope = upper
            self.lower_envelope = lower
            self.channel_width = width
            self.values = aligned_ema

            self.calculation_metadata = {
                'period': self.period,
                'multiplier': self.multiplier,
                'lookback': self.lookback,
                'data_points_used': len(data),
                'points_calculated': len(result),
                'last_ema': float(aligned_ema[-1]),
                'last_upper': float(upper[-1]),
                'last_lower': float(lower[-1]),
                'last_width': float(width[-1]),
                'last_pct_position': float(pct_position[-1]),
            }

            logger.debug(f"Calculated AutoEnvelope with {len(result)} values")
            return result

        except Exception as e:
            logger.error(f"Error calculating AutoEnvelope: {e}")
            raise

    def _calculate_ema(self, data: np.ndarray, period: int) -> np.ndarray:
        alpha = 2.0 / (period + 1)
        result = np.zeros(len(data))
        result[period - 1] = np.mean(data[:period])
        for i in range(period, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
        return result

    # --- Public getters ---

    def get_upper(self, index: Optional[int] = None) -> Optional[float]:
        if self.upper_envelope is None or len(self.upper_envelope) == 0:
            return None
        idx = index if index is not None else -1
        return float(self.upper_envelope[idx])

    def get_lower(self, index: Optional[int] = None) -> Optional[float]:
        if self.lower_envelope is None or len(self.lower_envelope) == 0:
            return None
        idx = index if index is not None else -1
        return float(self.lower_envelope[idx])

    def get_channel_width(self, index: Optional[int] = None) -> Optional[float]:
        if self.channel_width is None or len(self.channel_width) == 0:
            return None
        idx = index if index is not None else -1
        return float(self.channel_width[idx])

    def is_at_upper_envelope(self, price: float, threshold: float = 0.95) -> bool:
        """Check if price is near upper envelope (overbought)."""
        if self.upper_envelope is None or self.lower_envelope is None:
            return False
        width = self.upper_envelope[-1] - self.lower_envelope[-1]
        if width <= 0:
            return False
        pct = (price - self.lower_envelope[-1]) / width
        return bool(pct >= threshold)

    def is_at_lower_envelope(self, price: float, threshold: float = 0.05) -> bool:
        """Check if price is near lower envelope (oversold)."""
        if self.upper_envelope is None or self.lower_envelope is None:
            return False
        width = self.upper_envelope[-1] - self.lower_envelope[-1]
        if width <= 0:
            return False
        pct = (price - self.lower_envelope[-1]) / width
        return bool(pct <= threshold)

    def get_signal_summary(self) -> Dict[str, Any]:
        if self.ema_values is None:
            return {'status': 'no_data'}
        return {
            'ema': float(self.ema_values[-1]),
            'upper': float(self.upper_envelope[-1]),
            'lower': float(self.lower_envelope[-1]),
            'width': float(self.channel_width[-1]),
        }

    def get_required_data_points(self) -> int:
        return max(self.period, self.lookback) + 1
