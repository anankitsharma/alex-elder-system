"""
SafeZone Indicator V2 - Pine Script Compatible

Dynamic stop loss levels based on high/low penetration logic.
Exact translation of the Pine Script SafeZone indicator.

Pine Script Logic:
  Short-side: high > high[1] ? (high - high[1]) : 0
  Long-side:  low < low[1] ? (low[1] - low) : 0
  penAvg = totalSum / totalCount
  safetyShort = high[1] + (penAvg[1] * coeff)
  safetyLong  = low[1] - (penAvg[1] * coeff)
  short_stop = min(min(safety, safety[1]), safety[2])
  long_stop  = max(max(safety, safety[1]), safety[2])
  Progressive stops: shortvs/longvs with carry-over logic
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from loguru import logger
from .base import BaseIndicator


class SafeZoneV2(BaseIndicator):
    """
    SafeZone indicator V2 - Pine Script compatible implementation.

    Config:
    - lookback_length: Number of periods to look back (default: 22)
    - coefficient: Multiplier for safety calculation (default: 2.0)
    - progressive_mode: Enable progressive stop logic (default: True)
    """

    def __init__(self, symbol: str, timeframe: str, config: Dict[str, Any]):
        self.lookback_length = config.get('lookback_length', 22)
        self.coefficient = config.get('coefficient', 2.0)
        self.progressive_mode = config.get('progressive_mode', True)

        super().__init__(symbol, timeframe, config)

        self.high_prices = None
        self.low_prices = None
        self.close_prices = None

        self.count_short = None
        self.diff_short = None
        self.total_count_short = None
        self.total_sum_short = None
        self.pen_avg_short = None
        self.safety_short = None
        self.short_stop = None
        self.shortvs = None

        self.count_long = None
        self.diff_long = None
        self.total_count_long = None
        self.total_sum_long = None
        self.pen_avg_long = None
        self.safety_long = None
        self.long_stop = None
        self.longvs = None

    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate SafeZone V2 values using prefix-sum optimized O(N) algorithm.

        Replaces the original O(N × lookback × 6) nested loops with prefix-sum
        arrays for O(1) window lookups. Produces identical results.
        """
        if not self.validate_data(data):
            raise ValueError("Invalid data for SafeZone V2 calculation")

        if not self.is_ready_for_calculation(data):
            raise ValueError("Insufficient data for SafeZone V2 calculation")

        try:
            high_prices = data['high'].values
            low_prices = data['low'].values
            close_prices = data['close'].values
            datetime_values = data['datetime'].values

            length = len(data)

            longvs_array = np.full(length, np.nan)
            shortvs_array = np.full(length, np.nan)
            long_stop_array = np.full(length, np.nan)
            short_stop_array = np.full(length, np.nan)

            # ── Pre-compute per-bar penetration flags and diffs (O(N)) ──
            # Short-side: high[j] > high[j-1]
            count_short = np.zeros(length, dtype=np.float64)
            diff_short = np.zeros(length, dtype=np.float64)
            # Long-side: low[j] < low[j-1]
            count_long = np.zeros(length, dtype=np.float64)
            diff_long = np.zeros(length, dtype=np.float64)

            for j in range(1, length):
                if high_prices[j] > high_prices[j - 1]:
                    count_short[j] = 1.0
                    diff_short[j] = high_prices[j] - high_prices[j - 1]
                if low_prices[j] < low_prices[j - 1]:
                    count_long[j] = 1.0
                    diff_long[j] = low_prices[j - 1] - low_prices[j]

            # ── Build prefix sums (O(N)) ──
            prefix_count_short = np.cumsum(count_short)
            prefix_sum_short = np.cumsum(diff_short)
            prefix_count_long = np.cumsum(count_long)
            prefix_sum_long = np.cumsum(diff_long)

            def _window_pen_avg(prefix_count, prefix_sum, start, end):
                """O(1) pen_avg for window [start, end] using prefix sums."""
                total_count = prefix_count[end] - (prefix_count[start - 1] if start > 0 else 0)
                total_sum = prefix_sum[end] - (prefix_sum[start - 1] if start > 0 else 0)
                return total_sum / total_count if total_count > 0 else 0.0

            # ── Compute stops for each bar (O(N)) ──
            lb = self.lookback_length
            coeff = self.coefficient

            for i in range(1, length):
                start_idx = max(0, i - lb + 1)

                # --- Short-side ---
                # pen_avg for window ending at i-1 (prev bar's window)
                if i > 1:
                    prev_start = max(0, i - lb)
                    prev_pen_avg_short = _window_pen_avg(
                        prefix_count_short, prefix_sum_short, prev_start, i - 1
                    )
                else:
                    prev_pen_avg_short = 0.0

                safety_short = high_prices[i - 1] + (prev_pen_avg_short * coeff)

                # safety at i-1 and i-2 for the 3-bar min
                safety_short_1 = safety_short
                safety_short_2 = safety_short

                if i > 1:
                    prev2_start = max(0, i - 1 - lb)
                    prev2_pen_avg_short = _window_pen_avg(
                        prefix_count_short, prefix_sum_short, prev2_start, i - 2
                    ) if i - 2 >= 0 else 0.0
                    safety_short_1 = high_prices[i - 2] + (prev2_pen_avg_short * coeff)

                if i > 2:
                    prev3_start = max(0, i - 2 - lb)
                    prev3_pen_avg_short = _window_pen_avg(
                        prefix_count_short, prefix_sum_short, prev3_start, i - 3
                    ) if i - 3 >= 0 else 0.0
                    safety_short_2 = high_prices[i - 3] + (prev3_pen_avg_short * coeff)

                short_stop = min(safety_short, safety_short_1, safety_short_2)
                short_stop_array[i] = short_stop

                # Progressive short stop
                if i == 1 or np.isnan(shortvs_array[i - 1]):
                    shortvs_array[i] = short_stop
                else:
                    if close_prices[i] > shortvs_array[i - 1]:
                        shortvs_array[i] = short_stop
                    else:
                        shortvs_array[i] = min(short_stop, shortvs_array[i - 1])

                # --- Long-side ---
                if i > 1:
                    prev_pen_avg_long = _window_pen_avg(
                        prefix_count_long, prefix_sum_long, prev_start, i - 1
                    )
                else:
                    prev_pen_avg_long = 0.0

                safety_long = low_prices[i - 1] - (prev_pen_avg_long * coeff)

                safety_long_1 = safety_long
                safety_long_2 = safety_long

                if i > 1:
                    prev2_pen_avg_long = _window_pen_avg(
                        prefix_count_long, prefix_sum_long, prev2_start, i - 2
                    ) if i - 2 >= 0 else 0.0
                    safety_long_1 = low_prices[i - 2] - (prev2_pen_avg_long * coeff)

                if i > 2:
                    prev3_pen_avg_long = _window_pen_avg(
                        prefix_count_long, prefix_sum_long, prev3_start, i - 3
                    ) if i - 3 >= 0 else 0.0
                    safety_long_2 = low_prices[i - 3] - (prev3_pen_avg_long * coeff)

                long_stop = max(safety_long, safety_long_1, safety_long_2)
                long_stop_array[i] = long_stop

                # Progressive long stop
                if i == 1 or np.isnan(longvs_array[i - 1]):
                    longvs_array[i] = long_stop
                else:
                    if close_prices[i] < longvs_array[i - 1]:
                        longvs_array[i] = long_stop
                    else:
                        longvs_array[i] = max(long_stop, longvs_array[i - 1])

            result = pd.DataFrame({
                'datetime': datetime_values,
                'value': longvs_array,
                'longvs': longvs_array,
                'shortvs': shortvs_array,
                'long_stop': long_stop_array,
                'short_stop': short_stop_array
            })

            self.longvs = longvs_array
            self.shortvs = shortvs_array
            self.long_stop = long_stop_array
            self.short_stop = short_stop_array
            self.values = longvs_array

            self.calculation_metadata = {
                'lookback_length': self.lookback_length,
                'coefficient': self.coefficient,
                'progressive_mode': self.progressive_mode,
                'data_points_used': len(data),
                'safezone_points_calculated': len(result),
                'last_longvs': longvs_array[-1] if len(longvs_array) > 0 else None,
                'last_shortvs': shortvs_array[-1] if len(shortvs_array) > 0 else None
            }

            logger.debug(f"Calculated SafeZone V2 with {len(result)} values")
            return result

        except Exception as e:
            logger.error(f"Error calculating SafeZone V2: {e}")
            raise

    def validate_config(self) -> bool:
        try:
            if not isinstance(self.lookback_length, int) or self.lookback_length <= 0:
                logger.error(f"Invalid lookback_length: {self.lookback_length}")
                return False
            if not isinstance(self.coefficient, (int, float)) or self.coefficient <= 0:
                logger.error(f"Invalid coefficient: {self.coefficient}")
                return False
            if not isinstance(self.progressive_mode, bool):
                logger.error(f"Invalid progressive_mode: {self.progressive_mode}")
                return False
            return True
        except Exception as e:
            logger.error(f"Error validating SafeZone V2 config: {e}")
            return False

    def get_required_data_points(self) -> int:
        return max(self.lookback_length + 10, 25)

    # --- Public getters ---

    def get_short_stop(self, index: Optional[int] = None) -> Optional[float]:
        if self.shortvs is None:
            return None
        if index is None:
            return self.shortvs[-1] if len(self.shortvs) > 0 else None
        if 0 <= index < len(self.shortvs):
            return self.shortvs[index]
        return None

    def get_long_stop(self, index: Optional[int] = None) -> Optional[float]:
        if self.longvs is None:
            return None
        if index is None:
            return self.longvs[-1] if len(self.longvs) > 0 else None
        if 0 <= index < len(self.longvs):
            return self.longvs[index]
        return None

    def get_penetration_averages(self, index: Optional[int] = None) -> Dict[str, Optional[float]]:
        return {'short_pen_avg': None, 'long_pen_avg': None}

    def get_safety_levels(self, index: Optional[int] = None) -> Dict[str, Optional[float]]:
        return {'safety_short': None, 'safety_long': None}

    def calculate_stoploss_level(self, entry_price: float, trade_direction: str) -> Optional[float]:
        if trade_direction.upper() == 'LONG':
            return self.get_long_stop()
        elif trade_direction.upper() == 'SHORT':
            return self.get_short_stop()
        else:
            logger.error(f"Invalid trade direction: {trade_direction}")
            return None

    def calculate_risk_amount(self, entry_price: float, trade_direction: str) -> Optional[float]:
        stoploss = self.calculate_stoploss_level(entry_price, trade_direction)
        if stoploss is None:
            return None
        if trade_direction.upper() == 'LONG':
            return abs(entry_price - stoploss)
        elif trade_direction.upper() == 'SHORT':
            return abs(stoploss - entry_price)
        return None

    def calculate_position_size(self, entry_price: float, account_balance: float,
                                risk_percentage: float = 1.0, trade_direction: str = 'LONG') -> Optional[float]:
        risk_amount = self.calculate_risk_amount(entry_price, trade_direction)
        if risk_amount is None or risk_amount == 0:
            return None
        risk_dollar = account_balance * (risk_percentage / 100)
        return risk_dollar / risk_amount

    def update_with_new_data(self, new_candle: Dict[str, Any]) -> bool:
        logger.warning("SafeZone V2 incremental update not implemented, full recalculation required")
        return False

    def get_indicator_info(self) -> Dict[str, Any]:
        return {
            'name': 'SafeZone V2',
            'version': '2.0.0',
            'description': 'Pine Script compatible SafeZone indicator with progressive stops',
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'lookback_length': self.lookback_length,
            'coefficient': self.coefficient,
            'progressive_mode': self.progressive_mode,
            'last_longvs': self.get_long_stop(),
            'last_shortvs': self.get_short_stop(),
            'calculation_metadata': getattr(self, 'calculation_metadata', {})
        }
