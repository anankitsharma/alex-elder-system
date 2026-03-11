"""
Elder-Ray Index — Bull Power & Bear Power

Elder-Ray measures the power of bulls and bears relative to EMA-13.
- Bull Power = High - EMA(13) → measures distance bulls push price above consensus
- Bear Power = Low - EMA(13) → measures how far bears push price below consensus

Trading Rules (from Elder's "Trading for a Living"):
- BUY when: EMA-13 rising + Bear Power negative but rising (divergence from zero)
- SELL when: EMA-13 falling + Bull Power positive but falling
- Best buy: Bear Power dips below zero then turns up while EMA-13 still rising
- Best sell: Bull Power rises above zero then turns down while EMA-13 still falling
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from loguru import logger
from .base import BaseIndicator


class ElderRay(BaseIndicator):
    """
    Elder-Ray Index — Bull Power and Bear Power.

    Bull Power = High - EMA(period)
    Bear Power = Low - EMA(period)

    Features:
    - Configurable EMA period (default 13)
    - Bull/Bear power trend detection
    - Buy/Sell signal generation based on Elder's rules
    - Divergence detection (power vs price)
    """

    def __init__(self, symbol: str, timeframe: str, config: Dict[str, Any]):
        self.period = config.get('period', 13)
        self.source = config.get('source', 'close')

        super().__init__(symbol, timeframe, config)

        self.ema_values = None
        self.bull_power = None
        self.bear_power = None

    def validate_config(self) -> bool:
        if not isinstance(self.period, int) or self.period <= 0:
            logger.error(f"Invalid period: {self.period}")
            return False
        return True

    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate Elder-Ray Bull Power and Bear Power."""
        if not self.validate_data(data):
            raise ValueError("Invalid data for Elder-Ray calculation")

        if len(data) < self.period + 1:
            raise ValueError(f"Insufficient data: need at least {self.period + 1} bars")

        try:
            source_data = data[self.source].values if self.source in data.columns else data['close'].values

            # Calculate EMA
            ema = self._calculate_ema(source_data, self.period)

            # Trim to valid EMA range (first period-1 values are zero/invalid)
            start_idx = self.period - 1
            aligned_ema = ema[start_idx:]
            aligned_high = data['high'].values[start_idx:]
            aligned_low = data['low'].values[start_idx:]
            aligned_datetime = data['datetime'].values[start_idx:]

            # Bull Power = High - EMA
            bull_power = aligned_high - aligned_ema
            # Bear Power = Low - EMA
            bear_power = aligned_low - aligned_ema

            result = pd.DataFrame({
                'datetime': aligned_datetime,
                'ema': aligned_ema,
                'bull_power': bull_power,
                'bear_power': bear_power,
                'value': bull_power  # Primary value for base class
            })

            self.ema_values = aligned_ema
            self.bull_power = bull_power
            self.bear_power = bear_power
            self.values = bull_power

            self.calculation_metadata = {
                'period': self.period,
                'data_points_used': len(data),
                'points_calculated': len(result),
                'last_ema': float(aligned_ema[-1]),
                'last_bull_power': float(bull_power[-1]),
                'last_bear_power': float(bear_power[-1]),
            }

            logger.debug(f"Calculated Elder-Ray with {len(result)} values")
            return result

        except Exception as e:
            logger.error(f"Error calculating Elder-Ray: {e}")
            raise

    def _calculate_ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """Calculate EMA matching Pine Script ta.ema()."""
        alpha = 2.0 / (period + 1)
        result = np.zeros(len(data))
        result[period - 1] = np.mean(data[:period])
        for i in range(period, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
        return result

    # --- Public getters ---

    def get_bull_power(self, index: Optional[int] = None) -> Optional[float]:
        if self.bull_power is None or len(self.bull_power) == 0:
            return None
        if index is None:
            return float(self.bull_power[-1])
        if 0 <= index < len(self.bull_power):
            return float(self.bull_power[index])
        return None

    def get_bear_power(self, index: Optional[int] = None) -> Optional[float]:
        if self.bear_power is None or len(self.bear_power) == 0:
            return None
        if index is None:
            return float(self.bear_power[-1])
        if 0 <= index < len(self.bear_power):
            return float(self.bear_power[index])
        return None

    def get_ema_value(self, index: Optional[int] = None) -> Optional[float]:
        if self.ema_values is None or len(self.ema_values) == 0:
            return None
        if index is None:
            return float(self.ema_values[-1])
        if 0 <= index < len(self.ema_values):
            return float(self.ema_values[index])
        return None

    def get_ema_trend(self, periods: int = 2) -> str:
        """Get EMA trend direction."""
        if self.ema_values is None or len(self.ema_values) < periods:
            return 'UNKNOWN'
        recent = self.ema_values[-periods:]
        if recent[-1] > recent[0]:
            return 'RISING'
        elif recent[-1] < recent[0]:
            return 'FALLING'
        return 'FLAT'

    def get_bull_power_trend(self, periods: int = 3) -> str:
        if self.bull_power is None or len(self.bull_power) < periods:
            return 'UNKNOWN'
        recent = self.bull_power[-periods:]
        if all(recent[i] > recent[i - 1] for i in range(1, len(recent))):
            return 'RISING'
        elif all(recent[i] < recent[i - 1] for i in range(1, len(recent))):
            return 'FALLING'
        return 'MIXED'

    def get_bear_power_trend(self, periods: int = 3) -> str:
        if self.bear_power is None or len(self.bear_power) < periods:
            return 'UNKNOWN'
        recent = self.bear_power[-periods:]
        if all(recent[i] > recent[i - 1] for i in range(1, len(recent))):
            return 'RISING'
        elif all(recent[i] < recent[i - 1] for i in range(1, len(recent))):
            return 'FALLING'
        return 'MIXED'

    def get_buy_signal(self) -> bool:
        """
        Elder's Buy Rule:
        - EMA-13 rising (trend up)
        - Bear Power negative but rising (bears losing grip)
        """
        if self.bear_power is None or len(self.bear_power) < 3:
            return False
        if self.ema_values is None or len(self.ema_values) < 2:
            return False

        ema_rising = self.ema_values[-1] > self.ema_values[-2]
        bear_negative = self.bear_power[-1] < 0
        bear_rising = self.bear_power[-1] > self.bear_power[-2]

        return bool(ema_rising and bear_negative and bear_rising)

    def get_sell_signal(self) -> bool:
        """
        Elder's Sell Rule:
        - EMA-13 falling (trend down)
        - Bull Power positive but falling (bulls losing grip)
        """
        if self.bull_power is None or len(self.bull_power) < 3:
            return False
        if self.ema_values is None or len(self.ema_values) < 2:
            return False

        ema_falling = self.ema_values[-1] < self.ema_values[-2]
        bull_positive = self.bull_power[-1] > 0
        bull_falling = self.bull_power[-1] < self.bull_power[-2]

        return bool(ema_falling and bull_positive and bull_falling)

    def get_signal_summary(self) -> Dict[str, Any]:
        if self.bull_power is None or self.bear_power is None:
            return {'status': 'no_data'}
        return {
            'bull_power': float(self.bull_power[-1]),
            'bear_power': float(self.bear_power[-1]),
            'ema': float(self.ema_values[-1]) if self.ema_values is not None else None,
            'ema_trend': self.get_ema_trend(),
            'bull_power_trend': self.get_bull_power_trend(),
            'bear_power_trend': self.get_bear_power_trend(),
            'buy_signal': self.get_buy_signal(),
            'sell_signal': self.get_sell_signal(),
        }

    def get_required_data_points(self) -> int:
        return self.period + 1
