"""
Base Indicator Class

Abstract base class for all indicators in the Elder's Trading System.
Provides common functionality and interface for all indicators.
"""

import pandas as pd
import numpy as np
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime
from loguru import logger


class BaseIndicator(ABC):
    """
    Abstract base class for all indicators.

    Provides common interface and functionality: data validation,
    configuration management, slope/trend utilities.
    """

    def __init__(self, symbol: str, timeframe: str, config: Dict[str, Any]):
        self.symbol = symbol
        self.timeframe = timeframe
        self.config = config
        self.data = None
        self.values = None
        self.is_calculated = False
        self.last_calculation_time = None
        self.calculation_metadata = {}

        if not self.validate_config():
            raise ValueError(f"Invalid configuration for {self.__class__.__name__}")

        logger.info(f"Initialized {self.__class__.__name__} for {symbol} {timeframe}")

    @abstractmethod
    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate indicator values.

        Args:
            data: OHLC data with columns ['datetime', 'open', 'high', 'low', 'close', 'volume']

        Returns:
            DataFrame with indicator values
        """
        pass

    @abstractmethod
    def validate_config(self) -> bool:
        """Validate indicator configuration."""
        pass

    def get_latest_value(self) -> Optional[float]:
        """Get the latest calculated indicator value."""
        if self.values is not None and len(self.values) > 0:
            return float(self.values[-1])
        return None

    def get_slope(self, periods: int = 2) -> Optional[float]:
        """Calculate slope of indicator over specified periods."""
        if self.values is None or len(self.values) < periods:
            return None

        recent_values = self.values[-periods:]
        if len(recent_values) < periods:
            return None

        x = np.arange(len(recent_values))
        y = recent_values

        if len(x) != len(y):
            return None

        slope = (y[-1] - y[0]) / (len(y) - 1) if len(y) > 1 else 0
        return slope

    def get_trend_direction(self, periods: int = 2) -> str:
        """Determine trend direction based on indicator slope."""
        slope = self.get_slope(periods)
        if slope is None:
            return 'UNKNOWN'

        if slope > 0.001:
            return 'UP'
        elif slope < -0.001:
            return 'DOWN'
        else:
            return 'SIDEWAYS'

    def update_with_new_data(self, new_candle: Dict[str, Any]) -> bool:
        """Update indicator with new candle data (full recalculation)."""
        try:
            if self.data is None:
                logger.warning("No existing data to update")
                return False

            new_row = pd.DataFrame([new_candle])
            self.data = pd.concat([self.data, new_row], ignore_index=True)

            self.values = self.calculate(self.data)
            self.is_calculated = True
            self.last_calculation_time = datetime.now()

            logger.debug(f"Updated {self.__class__.__name__} with new candle")
            return True

        except Exception as e:
            logger.error(f"Error updating {self.__class__.__name__}: {e}")
            return False

    def get_calculation_metadata(self) -> Dict[str, Any]:
        """Get metadata about the last calculation."""
        return {
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'indicator_type': self.__class__.__name__,
            'is_calculated': self.is_calculated,
            'last_calculation_time': self.last_calculation_time,
            'data_points': len(self.data) if self.data is not None else 0,
            'indicator_points': len(self.values) if self.values is not None else 0,
            'config': self.config,
            'metadata': self.calculation_metadata
        }

    def validate_data(self, data: pd.DataFrame) -> bool:
        """Validate input data format and completeness."""
        if data is None or data.empty:
            logger.warning("Data is None or empty")
            return False

        required_columns = ['datetime', 'open', 'high', 'low', 'close']
        missing_columns = [col for col in required_columns if col not in data.columns]

        if missing_columns:
            logger.error(f"Missing required columns: {missing_columns}")
            return False

        for col in required_columns:
            if data[col].isna().any():
                logger.warning(f"NaN values found in column: {col}")
                return False

        if not self._validate_ohlc_consistency(data):
            logger.warning("OHLC data consistency check failed, but continuing")

        return True

    def _validate_ohlc_consistency(self, data: pd.DataFrame) -> bool:
        """Validate OHLC data consistency."""
        try:
            if not (data['high'] >= data['low']).all():
                return False
            if not (data['high'] >= data['open']).all():
                return False
            if not (data['high'] >= data['close']).all():
                return False
            if not (data['low'] <= data['open']).all():
                return False
            if not (data['low'] <= data['close']).all():
                return False
            return True
        except Exception as e:
            logger.error(f"Error validating OHLC consistency: {e}")
            return False

    def get_required_data_points(self) -> int:
        """Get minimum number of data points required for calculation."""
        return 1

    def is_ready_for_calculation(self, data: pd.DataFrame) -> bool:
        """Check if indicator has enough data for calculation."""
        if not self.validate_data(data):
            return False

        required_points = self.get_required_data_points()
        if len(data) < required_points:
            logger.warning(f"Insufficient data points: {len(data)} < {required_points}")
            return False

        return True

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.symbol}, {self.timeframe})"

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}(symbol='{self.symbol}', "
                f"timeframe='{self.timeframe}', calculated={self.is_calculated})")
