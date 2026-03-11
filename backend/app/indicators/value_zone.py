"""
Value Zone — EMA 13-26 Channel

The Value Zone is the area between EMA-13 and EMA-26.
When price dips into this zone during an uptrend, it's a buying opportunity.
When price rallies into this zone during a downtrend, it's a selling opportunity.

Elder's Rule:
- In uptrend: buy when price enters Value Zone from above
- In downtrend: sell when price enters Value Zone from below
- The zone width indicates trend strength (wider = stronger momentum)
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from loguru import logger
from .base import BaseIndicator


class ValueZone(BaseIndicator):
    """
    Value Zone — EMA-13 / EMA-26 channel.

    Features:
    - Fast EMA (default 13) and Slow EMA (default 26) channel
    - Zone width as trend strength indicator
    - Price position relative to zone (above/in/below)
    - Entry signals when price enters zone during trend
    """

    def __init__(self, symbol: str, timeframe: str, config: Dict[str, Any]):
        self.fast_period = config.get('fast_period', 13)
        self.slow_period = config.get('slow_period', 26)
        self.source = config.get('source', 'close')

        super().__init__(symbol, timeframe, config)

        self.fast_ema = None
        self.slow_ema = None
        self.zone_width = None

    def validate_config(self) -> bool:
        if not isinstance(self.fast_period, int) or self.fast_period <= 0:
            logger.error(f"Invalid fast_period: {self.fast_period}")
            return False
        if not isinstance(self.slow_period, int) or self.slow_period <= 0:
            logger.error(f"Invalid slow_period: {self.slow_period}")
            return False
        if self.fast_period >= self.slow_period:
            logger.error(f"fast_period ({self.fast_period}) must be less than slow_period ({self.slow_period})")
            return False
        return True

    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate Value Zone (EMA-13/EMA-26 channel)."""
        if not self.validate_data(data):
            raise ValueError("Invalid data for Value Zone calculation")

        if len(data) < self.slow_period + 1:
            raise ValueError(f"Insufficient data: need at least {self.slow_period + 1} bars")

        try:
            source_data = data[self.source].values if self.source in data.columns else data['close'].values

            fast_ema = self._calculate_ema(source_data, self.fast_period)
            slow_ema = self._calculate_ema(source_data, self.slow_period)

            # Align to slow EMA start
            start_idx = self.slow_period - 1
            aligned_fast = fast_ema[start_idx:]
            aligned_slow = slow_ema[start_idx:]
            aligned_close = data['close'].values[start_idx:]
            aligned_datetime = data['datetime'].values[start_idx:]

            # Zone boundaries
            zone_upper = np.maximum(aligned_fast, aligned_slow)
            zone_lower = np.minimum(aligned_fast, aligned_slow)
            zone_width = zone_upper - zone_lower

            # Price position relative to zone
            position = np.where(
                aligned_close > zone_upper, 1.0,    # Above zone
                np.where(aligned_close < zone_lower, -1.0, 0.0)  # Below / In zone
            )

            result = pd.DataFrame({
                'datetime': aligned_datetime,
                'fast_ema': aligned_fast,
                'slow_ema': aligned_slow,
                'zone_upper': zone_upper,
                'zone_lower': zone_lower,
                'zone_width': zone_width,
                'position': position,
                'value': zone_width  # Primary value
            })

            self.fast_ema = aligned_fast
            self.slow_ema = aligned_slow
            self.zone_width = zone_width
            self.values = zone_width

            self.calculation_metadata = {
                'fast_period': self.fast_period,
                'slow_period': self.slow_period,
                'data_points_used': len(data),
                'points_calculated': len(result),
                'last_fast_ema': float(aligned_fast[-1]),
                'last_slow_ema': float(aligned_slow[-1]),
                'last_zone_width': float(zone_width[-1]),
                'last_position': float(position[-1]),
            }

            logger.debug(f"Calculated Value Zone with {len(result)} values")
            return result

        except Exception as e:
            logger.error(f"Error calculating Value Zone: {e}")
            raise

    def _calculate_ema(self, data: np.ndarray, period: int) -> np.ndarray:
        alpha = 2.0 / (period + 1)
        result = np.zeros(len(data))
        result[period - 1] = np.mean(data[:period])
        for i in range(period, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
        return result

    # --- Public getters ---

    def get_fast_ema(self, index: Optional[int] = None) -> Optional[float]:
        if self.fast_ema is None or len(self.fast_ema) == 0:
            return None
        idx = index if index is not None else -1
        if 0 <= idx < len(self.fast_ema) or idx == -1:
            return float(self.fast_ema[idx])
        return None

    def get_slow_ema(self, index: Optional[int] = None) -> Optional[float]:
        if self.slow_ema is None or len(self.slow_ema) == 0:
            return None
        idx = index if index is not None else -1
        if 0 <= idx < len(self.slow_ema) or idx == -1:
            return float(self.slow_ema[idx])
        return None

    def get_zone_width(self, index: Optional[int] = None) -> Optional[float]:
        if self.zone_width is None or len(self.zone_width) == 0:
            return None
        idx = index if index is not None else -1
        if 0 <= idx < len(self.zone_width) or idx == -1:
            return float(self.zone_width[idx])
        return None

    def is_price_in_zone(self, price: float) -> bool:
        """Check if price is inside the Value Zone."""
        if self.fast_ema is None or self.slow_ema is None:
            return False
        upper = max(self.fast_ema[-1], self.slow_ema[-1])
        lower = min(self.fast_ema[-1], self.slow_ema[-1])
        return bool(lower <= price <= upper)

    def is_price_above_zone(self, price: float) -> bool:
        if self.fast_ema is None or self.slow_ema is None:
            return False
        upper = max(self.fast_ema[-1], self.slow_ema[-1])
        return bool(price > upper)

    def is_price_below_zone(self, price: float) -> bool:
        if self.fast_ema is None or self.slow_ema is None:
            return False
        lower = min(self.fast_ema[-1], self.slow_ema[-1])
        return bool(price < lower)

    def get_trend_direction(self, periods: int = 2) -> str:
        """Uptrend when fast > slow, downtrend when fast < slow."""
        if self.fast_ema is None or self.slow_ema is None:
            return 'UNKNOWN'
        if self.fast_ema[-1] > self.slow_ema[-1]:
            return 'UP'
        elif self.fast_ema[-1] < self.slow_ema[-1]:
            return 'DOWN'
        return 'SIDEWAYS'

    def get_zone_entry_signal(self, price: float) -> Optional[str]:
        """
        Signal when price enters Value Zone.
        - BUY: uptrend + price enters zone from above (pullback)
        - SELL: downtrend + price enters zone from below (rally)
        """
        if self.fast_ema is None or self.slow_ema is None or len(self.fast_ema) < 2:
            return None

        in_zone = self.is_price_in_zone(price)
        if not in_zone:
            return None

        trend = self.get_trend_direction()
        if trend == 'UP':
            return 'BUY'
        elif trend == 'DOWN':
            return 'SELL'
        return None

    def get_signal_summary(self) -> Dict[str, Any]:
        if self.fast_ema is None or self.slow_ema is None:
            return {'status': 'no_data'}

        close = None
        return {
            'fast_ema': float(self.fast_ema[-1]),
            'slow_ema': float(self.slow_ema[-1]),
            'zone_width': float(self.zone_width[-1]) if self.zone_width is not None else None,
            'trend': self.get_trend_direction(),
            'bullish_zone': bool(self.fast_ema[-1] > self.slow_ema[-1]),
        }

    def get_required_data_points(self) -> int:
        return self.slow_period + 1
