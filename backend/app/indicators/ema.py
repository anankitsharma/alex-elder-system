"""
Enhanced EMA (Exponential Moving Average) Indicator
with Multiple MA Types and Bollinger Bands

Supports: SMA, EMA, SMMA/RMA, WMA, VWMA, Bollinger Bands.
Configurable source: open/high/low/close/hl2/hlc3/ohlc4.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from loguru import logger
from .base import BaseIndicator


class EMAEnhanced(BaseIndicator):
    """
    Enhanced EMA indicator with multiple MA types and Bollinger Bands.

    Features:
    - Primary EMA calculation
    - Multiple smoothing MA types (SMA, EMA, SMMA/RMA, WMA, VWMA)
    - Bollinger Bands with configurable standard deviation
    - Trend analysis and price relationship analysis
    """

    def __init__(self, symbol: str, timeframe: str, config: Dict[str, Any]):
        super().__init__(symbol, timeframe, config)

        self.period = config.get('period', 22)
        self.source = config.get('source', 'close')
        self.offset = config.get('offset', 0)

        self.ma_type = config.get('ma_type', 'None')
        self.ma_length = config.get('ma_length', 14)
        self.bb_multiplier = config.get('bb_multiplier', 2.0)

        self.alpha = 2.0 / (self.period + 1)

        self.ema_values = None
        self.smoothing_ma_values = None
        self.bb_upper = None
        self.bb_lower = None
        self.last_ema = None

    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate Enhanced EMA values with optional smoothing MA and Bollinger Bands."""
        if not self.validate_data(data):
            raise ValueError("Invalid data for Enhanced EMA calculation")

        if not self.is_ready_for_calculation(data):
            raise ValueError(f"Insufficient data for Enhanced EMA({self.period}) calculation")

        try:
            source_data = self._get_source_data(data)
            ema_values = self._calculate_ema(source_data)

            smoothing_ma = None
            bb_upper = None
            bb_lower = None

            if self.ma_type != 'None':
                smoothing_ma = self._calculate_smoothing_ma(ema_values, self.ma_type, self.ma_length)

                if self.ma_type == 'SMA + Bollinger Bands':
                    bb_upper, bb_lower = self._calculate_bollinger_bands(ema_values, self.ma_length, self.bb_multiplier)

            result_data = {
                'datetime': data['datetime'].iloc[self.period - 1:],
                'open': data['open'].iloc[self.period - 1:].values,
                'high': data['high'].iloc[self.period - 1:].values,
                'low': data['low'].iloc[self.period - 1:].values,
                'close': data['close'].iloc[self.period - 1:].values,
                'volume': data['volume'].iloc[self.period - 1:].values,
                'ema': ema_values,
                'value': ema_values
            }

            if smoothing_ma is not None:
                result_data['smoothing_ma'] = smoothing_ma

            if bb_upper is not None and bb_lower is not None:
                result_data['bb_upper'] = bb_upper
                result_data['bb_lower'] = bb_lower
                result_data['bb_middle'] = smoothing_ma

            result = pd.DataFrame(result_data)

            self.ema_values = ema_values
            self.smoothing_ma_values = smoothing_ma
            self.bb_upper = bb_upper
            self.bb_lower = bb_lower
            self.last_ema = ema_values[-1] if len(ema_values) > 0 else None
            self.values = ema_values

            self.calculation_metadata = {
                'period': self.period,
                'alpha': self.alpha,
                'source': self.source,
                'ma_type': self.ma_type,
                'ma_length': self.ma_length,
                'bb_multiplier': self.bb_multiplier,
                'data_points_used': len(data),
                'ema_points_calculated': len(result),
                'first_ema_value': ema_values[0] if len(ema_values) > 0 else None,
                'last_ema_value': self.last_ema
            }

            logger.debug(f"Calculated Enhanced EMA({self.period}) with {len(result)} values")
            return result

        except Exception as e:
            logger.error(f"Error calculating Enhanced EMA: {e}")
            raise

    def _get_source_data(self, data: pd.DataFrame) -> np.ndarray:
        """Get source data based on configuration."""
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

    def _calculate_ema(self, source_data: np.ndarray) -> np.ndarray:
        """Calculate EMA values."""
        ema_values = np.zeros(len(source_data))
        ema_values[self.period - 1] = np.mean(source_data[:self.period])

        for i in range(self.period, len(source_data)):
            ema_values[i] = self.alpha * source_data[i] + (1 - self.alpha) * ema_values[i - 1]

        return ema_values[self.period - 1:]

    def _calculate_smoothing_ma(self, data: np.ndarray, ma_type: str, length: int) -> np.ndarray:
        """Calculate smoothing moving average."""
        if len(data) < length:
            return np.full(len(data), np.nan)

        if ma_type == 'SMA':
            return self._calculate_sma(data, length)
        elif ma_type == 'EMA':
            return self._calculate_ema_smoothing(data, length)
        elif ma_type in ('SMMA', 'RMA'):
            return self._calculate_smma(data, length)
        elif ma_type == 'WMA':
            return self._calculate_wma(data, length)
        elif ma_type == 'VWMA':
            return self._calculate_vwma(data, length)
        else:
            return np.full(len(data), np.nan)

    def _calculate_sma(self, data: np.ndarray, length: int) -> np.ndarray:
        result = np.full(len(data), np.nan)
        for i in range(length - 1, len(data)):
            result[i] = np.mean(data[i - length + 1:i + 1])
        return result

    def _calculate_ema_smoothing(self, data: np.ndarray, length: int) -> np.ndarray:
        alpha = 2.0 / (length + 1)
        result = np.full(len(data), np.nan)
        result[length - 1] = np.mean(data[:length])
        for i in range(length, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
        return result

    def _calculate_smma(self, data: np.ndarray, length: int) -> np.ndarray:
        alpha = 1.0 / length
        result = np.full(len(data), np.nan)
        result[length - 1] = np.mean(data[:length])
        for i in range(length, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
        return result

    def _calculate_wma(self, data: np.ndarray, length: int) -> np.ndarray:
        result = np.full(len(data), np.nan)
        weights = np.arange(1, length + 1)
        for i in range(length - 1, len(data)):
            window = data[i - length + 1:i + 1]
            result[i] = np.sum(window * weights) / np.sum(weights)
        return result

    def _calculate_vwma(self, data: np.ndarray, length: int) -> np.ndarray:
        logger.warning("VWMA requires volume data, falling back to SMA")
        return self._calculate_sma(data, length)

    def _calculate_bollinger_bands(self, data: np.ndarray, length: int, multiplier: float) -> tuple:
        sma = self._calculate_sma(data, length)
        std_dev = np.full(len(data), np.nan)
        for i in range(length - 1, len(data)):
            window = data[i - length + 1:i + 1]
            std_dev[i] = np.std(window, ddof=0)
        upper_band = sma + (std_dev * multiplier)
        lower_band = sma - (std_dev * multiplier)
        return upper_band, lower_band

    # --- Public getters ---

    def get_ema_value(self, index: Optional[int] = None) -> Optional[float]:
        if self.ema_values is None or len(self.ema_values) == 0:
            return None
        if index is None:
            return self.ema_values[-1]
        if 0 <= index < len(self.ema_values):
            return self.ema_values[index]
        return None

    def get_smoothing_ma_value(self, index: Optional[int] = None) -> Optional[float]:
        if self.smoothing_ma_values is None or len(self.smoothing_ma_values) == 0:
            return None
        if index is None:
            return self.smoothing_ma_values[-1]
        if 0 <= index < len(self.smoothing_ma_values):
            return self.smoothing_ma_values[index]
        return None

    def get_bollinger_bands(self, index: Optional[int] = None) -> Optional[tuple]:
        if self.bb_upper is None or self.bb_lower is None:
            return None
        if index is None:
            return (self.bb_upper[-1], self.bb_lower[-1])
        if 0 <= index < len(self.bb_upper):
            return (self.bb_upper[index], self.bb_lower[index])
        return None

    def get_ema_trend_direction(self, periods: int = 2) -> str:
        if self.ema_values is None or len(self.ema_values) < periods:
            return 'UNKNOWN'
        recent_values = self.ema_values[-periods:]
        slope = (recent_values[-1] - recent_values[0]) / (len(recent_values) - 1)
        if slope > 0.001:
            return 'UP'
        elif slope < -0.001:
            return 'DOWN'
        return 'SIDEWAYS'

    def is_price_above_ema(self, price: float) -> bool:
        current_ema = self.get_ema_value()
        return current_ema is not None and price > current_ema

    def is_price_below_ema(self, price: float) -> bool:
        current_ema = self.get_ema_value()
        return current_ema is not None and price < current_ema

    def get_ema_distance_percentage(self, price: float) -> Optional[float]:
        current_ema = self.get_ema_value()
        if current_ema is None or current_ema == 0:
            return None
        return ((price - current_ema) / current_ema) * 100

    def validate_config(self) -> bool:
        try:
            if 'period' not in self.config:
                logger.error("Missing 'period' in Enhanced EMA configuration")
                return False

            period = self.config['period']
            if not isinstance(period, int) or period <= 0:
                logger.error(f"Invalid EMA period: {period}")
                return False

            ma_type = self.config.get('ma_type', 'None')
            valid_ma_types = ['None', 'SMA', 'EMA', 'SMMA', 'RMA', 'WMA', 'VWMA', 'SMA + Bollinger Bands']
            if ma_type not in valid_ma_types:
                logger.error(f"Invalid MA type: {ma_type}")
                return False

            if ma_type != 'None':
                ma_length = self.config.get('ma_length', 14)
                if not isinstance(ma_length, int) or ma_length <= 0:
                    logger.error(f"Invalid MA length: {ma_length}")
                    return False

            return True

        except Exception as e:
            logger.error(f"Error validating Enhanced EMA config: {e}")
            return False

    def get_required_data_points(self) -> int:
        return max(self.period, self.ma_length if self.ma_type != 'None' else 0)

    def get_indicator_info(self) -> Dict[str, Any]:
        return {
            'indicator_type': 'EMA_Enhanced',
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'period': self.period,
            'alpha': self.alpha,
            'source': self.source,
            'ma_type': self.ma_type,
            'ma_length': self.ma_length,
            'bb_multiplier': self.bb_multiplier,
            'is_calculated': self.is_calculated,
            'last_ema_value': self.last_ema,
            'trend_direction': self.get_ema_trend_direction(),
            'required_data_points': self.get_required_data_points(),
            'calculation_metadata': self.calculation_metadata
        }
