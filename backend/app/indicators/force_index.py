"""
Enhanced Force Index (EFI) Implementation
Based on Pine Script: efi = ta.ema(ta.change(close) * volume, length)

Volume-validated with zero-line cross detection and strength analysis.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from loguru import logger
from .base import BaseIndicator


class ForceIndexEnhanced(BaseIndicator):
    """
    Enhanced Force Index (EFI) - Pine Script compatible.

    Formula: efi = ta.ema(ta.change(close) * volume, length)

    Features:
    - Volume validation (error if no volume data)
    - Configurable length (default 13)
    - Zero line cross detection
    - Trend and strength analysis
    """

    def __init__(self, symbol: str, timeframe: str, config: Dict[str, Any]):
        self.length = config.get('length', 13)
        self.source = config.get('source', 'close')

        super().__init__(symbol, timeframe, config)

        self.efi_values = None
        self.raw_force = None

    def validate_config(self) -> bool:
        if not isinstance(self.length, int) or self.length <= 0:
            logger.error(f"Invalid length: {self.length}")
            return False
        return True

    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate Enhanced Force Index."""
        if len(data) < self.length + 1:
            raise ValueError(f"Insufficient data: need at least {self.length + 1} bars")

        if 'volume' not in data.columns:
            raise ValueError("No volume is provided by the data vendor.")

        volume_sum = data['volume'].sum()
        if volume_sum == 0:
            raise ValueError("No volume is provided by the data vendor.")

        try:
            source_data = self._get_source_data(data)
            volume_data = data['volume'].values

            # ta.change(close) = close[i] - close[i-1]
            price_change = np.full(len(source_data), np.nan)
            price_change[1:] = np.diff(source_data)

            raw_force = price_change * volume_data

            # EFI = EMA of raw force
            efi_values = self._calculate_ema(raw_force, self.length)

            # Find first valid EFI value
            efi_start_idx = None
            for i in range(len(efi_values)):
                if not np.isnan(efi_values[i]):
                    efi_start_idx = i
                    break

            if efi_start_idx is None:
                raise ValueError("No valid EFI values calculated")

            aligned_efi = efi_values[efi_start_idx:]
            aligned_datetime = data['datetime'].values[efi_start_idx:]
            aligned_raw_force = raw_force[efi_start_idx:]

            result = pd.DataFrame({
                'datetime': aligned_datetime,
                'efi': aligned_efi,
                'raw_force': aligned_raw_force,
                'value': aligned_efi
            })

            self.efi_values = aligned_efi
            self.raw_force = aligned_raw_force
            self.values = aligned_efi

            self.calculation_metadata = {
                'length': self.length,
                'source': self.source,
                'data_points_used': len(data),
                'efi_points_calculated': len(result),
                'last_efi_value': aligned_efi[-1] if len(aligned_efi) > 0 else None,
                'last_raw_force_value': aligned_raw_force[-1] if len(aligned_raw_force) > 0 else None,
                'volume_sum': volume_sum,
                'volume_available': True
            }

            logger.debug(f"Calculated Enhanced Force Index with {len(result)} values")
            return result

        except Exception as e:
            logger.error(f"Error calculating Enhanced Force Index: {e}")
            raise

    def _get_source_data(self, data: pd.DataFrame) -> np.ndarray:
        if self.source == 'close':
            return data['close'].values
        elif self.source == 'open':
            return data['open'].values
        elif self.source == 'high':
            return data['high'].values
        elif self.source == 'low':
            return data['low'].values
        else:
            logger.warning(f"Unknown source: {self.source}, using close")
            return data['close'].values

    def _calculate_ema(self, data: np.ndarray, length: int) -> np.ndarray:
        """Calculate EMA with SMA seed — consistent with all other indicators."""
        alpha = 2.0 / (length + 1)
        result = np.full(len(data), np.nan)

        # Collect first `length` non-NaN values for SMA seed
        valid_vals = []
        seed_idx = None
        for i in range(len(data)):
            if not np.isnan(data[i]):
                valid_vals.append(data[i])
                if len(valid_vals) == length:
                    seed_idx = i
                    break

        if seed_idx is None:
            return result

        result[seed_idx] = np.mean(valid_vals)

        for i in range(seed_idx + 1, len(data)):
            if not np.isnan(data[i]):
                result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
            else:
                result[i] = result[i - 1]

        return result

    # --- Public getters ---

    def get_efi_value(self, index: Optional[int] = None) -> Optional[float]:
        if self.efi_values is None or len(self.efi_values) == 0:
            return None
        if index is None:
            return self.efi_values[-1]
        if 0 <= index < len(self.efi_values):
            return self.efi_values[index]
        return None

    def get_efi_trend(self, periods: int = 3) -> str:
        if self.efi_values is None or len(self.efi_values) < periods:
            return 'UNKNOWN'
        recent_values = self.efi_values[-periods:]
        if all(recent_values[i] > recent_values[i-1] for i in range(1, len(recent_values))):
            return 'RISING'
        elif all(recent_values[i] < recent_values[i-1] for i in range(1, len(recent_values))):
            return 'FALLING'
        return 'SIDEWAYS'

    def is_above_zero(self) -> bool:
        efi_value = self.get_efi_value()
        return efi_value is not None and efi_value > 0

    def is_below_zero(self) -> bool:
        efi_value = self.get_efi_value()
        return efi_value is not None and efi_value < 0

    def get_zero_cross_signal(self) -> Optional[str]:
        if self.efi_values is None or len(self.efi_values) < 2:
            return None
        current = self.efi_values[-1]
        previous = self.efi_values[-2]
        if previous <= 0 and current > 0:
            return 'BULLISH'
        if previous >= 0 and current < 0:
            return 'BEARISH'
        return None

    def get_signal_summary(self) -> Dict[str, Any]:
        if self.efi_values is None or len(self.efi_values) == 0:
            return {'status': 'no_data'}
        return {
            'current_value': self.efi_values[-1],
            'above_zero': self.is_above_zero(),
            'below_zero': self.is_below_zero(),
            'trend': self.get_efi_trend(),
            'zero_cross_signal': self.get_zero_cross_signal(),
            'strength': self._calculate_strength()
        }

    def _calculate_strength(self) -> str:
        if self.efi_values is None or len(self.efi_values) == 0:
            return 'UNKNOWN'
        current_value = abs(self.efi_values[-1])
        avg_abs_value = np.mean(np.abs(self.efi_values[-10:])) if len(self.efi_values) >= 10 else current_value
        if current_value > avg_abs_value * 1.5:
            return 'STRONG'
        elif current_value > avg_abs_value * 0.5:
            return 'MODERATE'
        return 'WEAK'

    def get_required_data_points(self) -> int:
        return self.length + 1
