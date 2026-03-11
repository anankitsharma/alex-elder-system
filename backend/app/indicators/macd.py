"""
Enhanced MACD (Moving Average Convergence Divergence) Indicator
with configurable MA types and enhanced histogram

Supports SMA/EMA for both oscillator and signal line.
Pine Script compatible histogram color coding.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from loguru import logger
from .base import BaseIndicator


class MACDEnhanced(BaseIndicator):
    """
    Enhanced MACD indicator with configurable MA types and enhanced histogram.

    Features:
    - Configurable MA types (SMA/EMA) for oscillator and signal line
    - Enhanced histogram with Pine Script color coding
    - Crossover detection and trend analysis
    """

    def __init__(self, symbol: str, timeframe: str, config: Dict[str, Any]):
        self.fast_length = config.get('fast_length', 12)
        self.slow_length = config.get('slow_length', 26)
        self.signal_length = config.get('signal_length', 9)
        self.source = config.get('source', 'close')
        self.oscillator_ma_type = config.get('oscillator_ma_type', 'EMA')
        self.signal_ma_type = config.get('signal_ma_type', 'EMA')

        super().__init__(symbol, timeframe, config)

        self.fast_ma = None
        self.slow_ma = None
        self.signal_ma = None

        self.macd_line = None
        self.signal_line = None
        self.histogram = None

    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate Enhanced MACD values."""
        if not self.validate_data(data):
            raise ValueError("Invalid data for Enhanced MACD calculation")

        if not self.is_ready_for_calculation(data):
            raise ValueError("Insufficient data for Enhanced MACD calculation")

        try:
            source_data = self._get_source_data(data)

            fast_ma_values = self._calculate_ma(source_data, self.fast_length, self.oscillator_ma_type)
            slow_ma_values = self._calculate_ma(source_data, self.slow_length, self.oscillator_ma_type)

            macd_start_idx = max(self.fast_length - 1, self.slow_length - 1)
            macd_line = fast_ma_values[macd_start_idx:] - slow_ma_values[macd_start_idx:]
            datetime_values = data['datetime'].values[macd_start_idx:]

            valid_macd_mask = ~np.isnan(macd_line)
            if not np.any(valid_macd_mask):
                raise ValueError("No valid MACD values for signal calculation")

            valid_macd_line = macd_line[valid_macd_mask]
            valid_datetime = datetime_values[valid_macd_mask]

            signal_line = self._calculate_ma(valid_macd_line, self.signal_length, self.signal_ma_type)

            signal_length = len(signal_line)
            if signal_length == 0:
                raise ValueError("No signal line data available")

            aligned_macd_line = valid_macd_line[-signal_length:]
            aligned_datetime = valid_datetime[-signal_length:]
            aligned_signal_line = signal_line

            histogram = aligned_macd_line - aligned_signal_line

            result = pd.DataFrame({
                'datetime': aligned_datetime,
                'macd_line': aligned_macd_line,
                'signal_line': aligned_signal_line,
                'histogram': histogram,
                'value': aligned_macd_line
            })

            self.macd_line = aligned_macd_line
            self.signal_line = aligned_signal_line
            self.histogram = histogram
            self.values = aligned_macd_line

            self.calculation_metadata = {
                'fast_length': self.fast_length,
                'slow_length': self.slow_length,
                'signal_length': self.signal_length,
                'source': self.source,
                'oscillator_ma_type': self.oscillator_ma_type,
                'signal_ma_type': self.signal_ma_type,
                'data_points_used': len(data),
                'macd_points_calculated': len(result),
                'last_macd_value': aligned_macd_line[-1] if len(aligned_macd_line) > 0 else None,
                'last_signal_value': aligned_signal_line[-1] if len(aligned_signal_line) > 0 else None,
                'last_histogram_value': histogram[-1] if len(histogram) > 0 else None
            }

            logger.debug(f"Calculated Enhanced MACD with {len(result)} values")
            return result

        except Exception as e:
            logger.error(f"Error calculating Enhanced MACD: {e}")
            raise

    def _get_source_data(self, data: pd.DataFrame) -> np.ndarray:
        if self.source == 'open':
            return data['open'].values
        elif self.source == 'high':
            return data['high'].values
        elif self.source == 'low':
            return data['low'].values
        elif self.source == 'close':
            return data['close'].values
        elif self.source == 'hl2':
            return (data['high'] + data['low']).values / 2
        elif self.source == 'hlc3':
            return (data['high'] + data['low'] + data['close']).values / 3
        elif self.source == 'ohlc4':
            return (data['open'] + data['high'] + data['low'] + data['close']).values / 4
        else:
            return data['close'].values

    def _calculate_ma(self, data: np.ndarray, length: int, ma_type: str) -> np.ndarray:
        if ma_type == 'SMA':
            return self._calculate_sma(data, length)
        elif ma_type == 'EMA':
            return self._calculate_ema(data, length)
        else:
            logger.warning(f"Unknown MA type: {ma_type}, falling back to EMA")
            return self._calculate_ema(data, length)

    def _calculate_sma(self, data: np.ndarray, length: int) -> np.ndarray:
        result = np.full(len(data), np.nan)
        for i in range(length - 1, len(data)):
            result[i] = np.mean(data[i - length + 1:i + 1])
        return result

    def _calculate_ema(self, data: np.ndarray, length: int) -> np.ndarray:
        alpha = 2.0 / (length + 1)
        result = np.full(len(data), np.nan)
        result[length - 1] = np.mean(data[:length])
        for i in range(length, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
        return result

    # --- Public getters ---

    def get_macd_value(self, index: Optional[int] = None) -> Optional[float]:
        if self.macd_line is None or len(self.macd_line) == 0:
            return None
        if index is None:
            return self.macd_line[-1]
        if 0 <= index < len(self.macd_line):
            return self.macd_line[index]
        return None

    def get_signal_value(self, index: Optional[int] = None) -> Optional[float]:
        if self.signal_line is None or len(self.signal_line) == 0:
            return None
        if index is None:
            return self.signal_line[-1]
        if 0 <= index < len(self.signal_line):
            return self.signal_line[index]
        return None

    def get_histogram_value(self, index: Optional[int] = None) -> Optional[float]:
        if self.histogram is None or len(self.histogram) == 0:
            return None
        if index is None:
            return self.histogram[-1]
        if 0 <= index < len(self.histogram):
            return self.histogram[index]
        return None

    def get_histogram_trend_direction(self, periods: int = 2) -> str:
        if self.histogram is None or len(self.histogram) < periods:
            return 'UNKNOWN'
        recent_values = self.histogram[-periods:]
        slope = (recent_values[-1] - recent_values[0]) / (len(recent_values) - 1)
        if slope > 0.001:
            return 'UP'
        elif slope < -0.001:
            return 'DOWN'
        return 'SIDEWAYS'

    def is_macd_above_signal(self) -> bool:
        macd_value = self.get_macd_value()
        signal_value = self.get_signal_value()
        if macd_value is None or signal_value is None:
            return False
        return macd_value > signal_value

    def is_macd_below_signal(self) -> bool:
        macd_value = self.get_macd_value()
        signal_value = self.get_signal_value()
        if macd_value is None or signal_value is None:
            return False
        return macd_value < signal_value

    def get_macd_crossover_signal(self) -> Optional[str]:
        if self.macd_line is None or self.signal_line is None or len(self.macd_line) < 2:
            return None

        macd_current = self.macd_line[-1]
        macd_previous = self.macd_line[-2]
        signal_current = self.signal_line[-1]
        signal_previous = self.signal_line[-2]

        if macd_previous <= signal_previous and macd_current > signal_current:
            return 'BULLISH'
        if macd_previous >= signal_previous and macd_current < signal_current:
            return 'BEARISH'
        return None

    def get_histogram_color(self, index: Optional[int] = None) -> str:
        """Get histogram color based on Pine Script logic."""
        if index is None:
            index = -1
        if self.histogram is None or len(self.histogram) <= abs(index):
            return '#787B86'

        current_hist = self.histogram[index]
        previous_hist = self.histogram[index - 1] if index > 0 else current_hist

        if current_hist >= 0:
            if previous_hist < current_hist:
                return '#26A69A'  # Rising green
            else:
                return '#B2DFDB'  # Falling green
        else:
            if previous_hist < current_hist:
                return '#FFCDD2'  # Rising red
            else:
                return '#FF5252'  # Falling red

    def validate_config(self) -> bool:
        try:
            required_params = ['fast_length', 'slow_length', 'signal_length']
            for param in required_params:
                if param not in self.config:
                    logger.error(f"Missing '{param}' in Enhanced MACD configuration")
                    return False

            if not isinstance(self.fast_length, int) or self.fast_length <= 0:
                logger.error(f"Invalid fast length: {self.fast_length}")
                return False
            if not isinstance(self.slow_length, int) or self.slow_length <= 0:
                logger.error(f"Invalid slow length: {self.slow_length}")
                return False
            if not isinstance(self.signal_length, int) or self.signal_length <= 0:
                logger.error(f"Invalid signal length: {self.signal_length}")
                return False
            if self.fast_length >= self.slow_length:
                logger.error(f"Fast length ({self.fast_length}) must be less than slow length ({self.slow_length})")
                return False

            valid_ma_types = ['SMA', 'EMA']
            if self.oscillator_ma_type not in valid_ma_types:
                logger.error(f"Invalid oscillator MA type: {self.oscillator_ma_type}")
                return False
            if self.signal_ma_type not in valid_ma_types:
                logger.error(f"Invalid signal MA type: {self.signal_ma_type}")
                return False

            return True

        except Exception as e:
            logger.error(f"Error validating Enhanced MACD config: {e}")
            return False

    def get_required_data_points(self) -> int:
        return max(self.slow_length, self.signal_length)

    def get_indicator_info(self) -> Dict[str, Any]:
        return {
            'indicator_type': 'MACD_Enhanced',
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'fast_length': self.fast_length,
            'slow_length': self.slow_length,
            'signal_length': self.signal_length,
            'source': self.source,
            'oscillator_ma_type': self.oscillator_ma_type,
            'signal_ma_type': self.signal_ma_type,
            'is_calculated': self.is_calculated,
            'last_macd_value': self.get_macd_value(),
            'last_signal_value': self.get_signal_value(),
            'last_histogram_value': self.get_histogram_value(),
            'histogram_trend': self.get_histogram_trend_direction(),
            'crossover_signal': self.get_macd_crossover_signal(),
            'required_data_points': self.get_required_data_points(),
            'calculation_metadata': self.calculation_metadata
        }
