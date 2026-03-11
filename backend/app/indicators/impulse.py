"""
Enhanced Elder Impulse System Implementation

Combines EMA trend and MACD momentum to color bars:
  Green: Bullish (EMA rising AND MACD histogram rising)
  Red:   Bearish (EMA falling AND MACD histogram falling)
  Blue:  Neutral (mixed signals)
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from loguru import logger
from .base import BaseIndicator


class ElderImpulseEnhanced(BaseIndicator):
    """
    Enhanced Elder Impulse System.

    Combines EMA trend direction with MACD histogram momentum
    to produce color-coded bar signals per Dr. Alexander Elder's methodology.
    """

    def __init__(self, symbol: str, timeframe: str, config: Dict[str, Any]):
        self.macd_fast_length = config.get('macd_fast_length', 12)
        self.macd_slow_length = config.get('macd_slow_length', 26)
        self.macd_signal_length = config.get('macd_signal_length', 9)
        self.ema_length = config.get('ema_length', 13)
        self.source = config.get('source', 'close')

        self.bullish_color = config.get('bullish_color', 'green')
        self.bearish_color = config.get('bearish_color', 'red')
        self.neutral_color = config.get('neutral_color', 'blue')

        super().__init__(symbol, timeframe, config)

        self.ema_indicator = None
        self.macd_indicator = None

        self.impulse_colors = None
        self.impulse_signals = None
        self.ema_values = None
        self.macd_histogram = None

    def validate_config(self) -> bool:
        required_params = ['macd_fast_length', 'macd_slow_length', 'macd_signal_length', 'ema_length']

        for param in required_params:
            if param not in self.config:
                logger.error(f"Missing required parameter: {param}")
                return False

            if not isinstance(self.config[param], int) or self.config[param] <= 0:
                logger.error(f"Invalid {param}: must be positive integer")
                return False

        valid_colors = ['green', 'red', 'blue', 'yellow', 'orange', 'purple', 'cyan', 'magenta']
        color_params = ['bullish_color', 'bearish_color', 'neutral_color']

        for color_param in color_params:
            if color_param in self.config:
                if self.config[color_param] not in valid_colors:
                    logger.warning(f"Invalid color {self.config[color_param]} for {color_param}, using default")
                    self.config[color_param] = 'green' if 'bullish' in color_param else 'red' if 'bearish' in color_param else 'blue'

        return True

    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate Elder Impulse System signals."""
        if len(data) < max(self.macd_slow_length, self.ema_length) + 2:
            raise ValueError(f"Insufficient data: need at least {max(self.macd_slow_length, self.ema_length) + 2} bars")

        try:
            from .ema import EMAEnhanced
            from .macd import MACDEnhanced

            # Calculate EMA
            ema_config = {
                'period': self.ema_length,
                'source': self.source,
                'ma_type': 'None'
            }
            self.ema_indicator = EMAEnhanced(self.symbol, self.timeframe, ema_config)
            ema_result = self.ema_indicator.calculate(data)
            self.ema_values = ema_result['ema'].values

            # Calculate MACD
            macd_config = {
                'fast_length': self.macd_fast_length,
                'slow_length': self.macd_slow_length,
                'signal_length': self.macd_signal_length,
                'source': self.source,
                'oscillator_ma_type': 'EMA',
                'signal_ma_type': 'EMA'
            }
            self.macd_indicator = MACDEnhanced(self.symbol, self.timeframe, macd_config)
            macd_result = self.macd_indicator.calculate(data)
            self.macd_histogram = macd_result['histogram'].values

            # Align EMA and MACD data
            min_length = min(len(self.ema_values), len(self.macd_histogram))
            if min_length < 2:
                raise ValueError("Insufficient aligned data for impulse calculation")

            aligned_ema = self.ema_values[-min_length:]
            aligned_macd_hist = self.macd_histogram[-min_length:]
            aligned_datetime = data['datetime'].values[-min_length:]

            # Calculate Elder Impulse signals
            impulse_colors = []
            impulse_signals = []

            for i in range(len(aligned_ema)):
                if i < 1:
                    impulse_colors.append(self.neutral_color)
                    impulse_signals.append('neutral')
                    continue

                ema_rising = aligned_ema[i] > aligned_ema[i-1]
                ema_falling = aligned_ema[i] < aligned_ema[i-1]

                macd_rising = aligned_macd_hist[i] > aligned_macd_hist[i-1]
                macd_falling = aligned_macd_hist[i] < aligned_macd_hist[i-1]

                elder_bulls = ema_rising and macd_rising
                elder_bears = ema_falling and macd_falling

                if elder_bulls:
                    impulse_colors.append(self.bullish_color)
                    impulse_signals.append('bullish')
                elif elder_bears:
                    impulse_colors.append(self.bearish_color)
                    impulse_signals.append('bearish')
                else:
                    impulse_colors.append(self.neutral_color)
                    impulse_signals.append('neutral')

            result = pd.DataFrame({
                'datetime': aligned_datetime,
                'impulse_color': impulse_colors,
                'impulse_signal': impulse_signals,
                'ema_value': aligned_ema,
                'macd_histogram': aligned_macd_hist,
                'value': aligned_ema
            })

            self.impulse_colors = impulse_colors
            self.impulse_signals = impulse_signals
            self.values = aligned_ema

            self.calculation_metadata = {
                'macd_fast_length': self.macd_fast_length,
                'macd_slow_length': self.macd_slow_length,
                'macd_signal_length': self.macd_signal_length,
                'ema_length': self.ema_length,
                'source': self.source,
                'data_points_used': len(data),
                'impulse_points_calculated': len(result),
                'bullish_count': impulse_signals.count('bullish'),
                'bearish_count': impulse_signals.count('bearish'),
                'neutral_count': impulse_signals.count('neutral'),
                'last_impulse_signal': impulse_signals[-1] if impulse_signals else None,
                'last_ema_value': aligned_ema[-1] if len(aligned_ema) > 0 else None,
                'last_macd_histogram': aligned_macd_hist[-1] if len(aligned_macd_hist) > 0 else None
            }

            logger.debug(f"Calculated Elder Impulse with {len(result)} values")
            return result

        except Exception as e:
            logger.error(f"Error calculating Elder Impulse: {e}")
            raise

    # --- Public getters ---

    def get_impulse_signal(self, index: Optional[int] = None) -> Optional[str]:
        if self.impulse_signals is None or len(self.impulse_signals) == 0:
            return None
        if index is None:
            return self.impulse_signals[-1]
        if 0 <= index < len(self.impulse_signals):
            return self.impulse_signals[index]
        return None

    def get_impulse_color(self, index: Optional[int] = None) -> Optional[str]:
        if self.impulse_colors is None or len(self.impulse_colors) == 0:
            return None
        if index is None:
            return self.impulse_colors[-1]
        if 0 <= index < len(self.impulse_colors):
            return self.impulse_colors[index]
        return None

    def get_signal_summary(self) -> Dict[str, Any]:
        if self.impulse_signals is None or len(self.impulse_signals) == 0:
            return {'status': 'no_data'}

        recent_signals = self.impulse_signals[-10:] if len(self.impulse_signals) >= 10 else self.impulse_signals

        return {
            'current_signal': self.impulse_signals[-1],
            'current_color': self.impulse_colors[-1],
            'recent_bullish': recent_signals.count('bullish'),
            'recent_bearish': recent_signals.count('bearish'),
            'recent_neutral': recent_signals.count('neutral'),
            'trend_strength': self._calculate_trend_strength(),
            'momentum_strength': self._calculate_momentum_strength()
        }

    def _calculate_trend_strength(self) -> str:
        if self.ema_values is None or len(self.ema_values) < 5:
            return 'unknown'
        recent_ema = self.ema_values[-5:]
        if all(recent_ema[i] > recent_ema[i-1] for i in range(1, len(recent_ema))):
            return 'strong_bullish'
        elif all(recent_ema[i] < recent_ema[i-1] for i in range(1, len(recent_ema))):
            return 'strong_bearish'
        elif recent_ema[-1] > recent_ema[0]:
            return 'weak_bullish'
        elif recent_ema[-1] < recent_ema[0]:
            return 'weak_bearish'
        return 'sideways'

    def _calculate_momentum_strength(self) -> str:
        if self.macd_histogram is None or len(self.macd_histogram) < 5:
            return 'unknown'
        recent_hist = self.macd_histogram[-5:]
        if all(recent_hist[i] > recent_hist[i-1] for i in range(1, len(recent_hist))):
            return 'strong_bullish'
        elif all(recent_hist[i] < recent_hist[i-1] for i in range(1, len(recent_hist))):
            return 'strong_bearish'
        elif recent_hist[-1] > recent_hist[0]:
            return 'weak_bullish'
        elif recent_hist[-1] < recent_hist[0]:
            return 'weak_bearish'
        return 'sideways'

    def get_required_data_points(self) -> int:
        return max(self.macd_slow_length, self.ema_length) + 2
