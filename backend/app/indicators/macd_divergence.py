"""
MACD-Histogram Divergence Detector

Elder's most powerful signal. Divergence between MACD-Histogram and price
indicates exhaustion of the current trend.

Rules (from "Trading for a Living"):
1. MACD-H must cross zero line between the two peaks/troughs
2. Bullish divergence: price makes lower low, MACD-H makes higher trough
3. Bearish divergence: price makes higher high, MACD-H makes lower peak
4. The second peak/trough must be smaller in absolute value than the first
5. Zero-line crossing between peaks is MANDATORY (without it, it's not a true divergence)
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List, Tuple
from loguru import logger
from .base import BaseIndicator


class MACDDivergence(BaseIndicator):
    """
    MACD-Histogram Divergence Detector.

    Detects classic Elder divergences between MACD-H and price.
    Requires zero-line crossing between peaks/troughs (Elder's strict rule).

    Features:
    - Peak/trough detection on MACD-H
    - Zero-line crossing validation
    - Bullish divergence (price lower low + MACD-H higher trough)
    - Bearish divergence (price higher high + MACD-H lower peak)
    - Divergence strength scoring
    """

    def __init__(self, symbol: str, timeframe: str, config: Dict[str, Any]):
        self.fast_length = config.get('fast_length', 12)
        self.slow_length = config.get('slow_length', 26)
        self.signal_length = config.get('signal_length', 9)
        self.source = config.get('source', 'close')
        self.peak_lookback = config.get('peak_lookback', 5)  # Bars to confirm peak/trough

        super().__init__(symbol, timeframe, config)

        self.histogram = None
        self.peaks = None    # List of (index, value) for MACD-H peaks
        self.troughs = None  # List of (index, value) for MACD-H troughs
        self.divergences = None  # List of divergence signals

    def validate_config(self) -> bool:
        if not isinstance(self.fast_length, int) or self.fast_length <= 0:
            return False
        if not isinstance(self.slow_length, int) or self.slow_length <= 0:
            return False
        if not isinstance(self.signal_length, int) or self.signal_length <= 0:
            return False
        if self.fast_length >= self.slow_length:
            logger.error("fast_length must be less than slow_length")
            return False
        return True

    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate MACD-H and detect divergences."""
        if not self.validate_data(data):
            raise ValueError("Invalid data for MACD Divergence calculation")

        min_required = self.slow_length + self.signal_length + self.peak_lookback
        if len(data) < min_required:
            raise ValueError(f"Insufficient data: need at least {min_required} bars")

        try:
            source_data = data[self.source].values if self.source in data.columns else data['close'].values
            high_data = data['high'].values
            low_data = data['low'].values

            # Calculate MACD
            fast_ema = self._calculate_ema(source_data, self.fast_length)
            slow_ema = self._calculate_ema(source_data, self.slow_length)

            start_idx = self.slow_length - 1
            macd_line = fast_ema[start_idx:] - slow_ema[start_idx:]

            # Signal line
            signal_line = self._calculate_ema_from_valid(macd_line, self.signal_length)
            hist = macd_line - signal_line

            # Find first valid histogram value
            valid_start = None
            for i in range(len(hist)):
                if not np.isnan(hist[i]):
                    valid_start = i
                    break

            if valid_start is None:
                raise ValueError("No valid MACD histogram values")

            aligned_hist = hist[valid_start:]
            total_offset = start_idx + valid_start
            aligned_datetime = data['datetime'].values[total_offset:]
            aligned_close = source_data[total_offset:]
            aligned_high = high_data[total_offset:]
            aligned_low = low_data[total_offset:]

            # Detect peaks and troughs in MACD-H
            peaks = self._find_peaks(aligned_hist)
            troughs = self._find_troughs(aligned_hist)

            # Detect divergences
            divergences = self._detect_divergences(
                aligned_hist, aligned_high, aligned_low, aligned_close, peaks, troughs
            )

            # Build divergence signal array
            div_signal = np.zeros(len(aligned_hist))
            for div in divergences:
                div_signal[div['end_idx']] = 1.0 if div['type'] == 'BULLISH' else -1.0

            result = pd.DataFrame({
                'datetime': aligned_datetime,
                'histogram': aligned_hist,
                'divergence_signal': div_signal,
                'value': aligned_hist
            })

            self.histogram = aligned_hist
            self.peaks = peaks
            self.troughs = troughs
            self.divergences = divergences
            self.values = aligned_hist

            self.calculation_metadata = {
                'fast_length': self.fast_length,
                'slow_length': self.slow_length,
                'signal_length': self.signal_length,
                'data_points_used': len(data),
                'points_calculated': len(result),
                'peaks_found': len(peaks),
                'troughs_found': len(troughs),
                'divergences_found': len(divergences),
                'last_histogram': float(aligned_hist[-1]),
            }

            logger.debug(f"MACD Divergence: {len(divergences)} divergences found")
            return result

        except Exception as e:
            logger.error(f"Error calculating MACD Divergence: {e}")
            raise

    def _calculate_ema(self, data: np.ndarray, period: int) -> np.ndarray:
        alpha = 2.0 / (period + 1)
        result = np.zeros(len(data))
        result[period - 1] = np.mean(data[:period])
        for i in range(period, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
        return result

    def _calculate_ema_from_valid(self, data: np.ndarray, period: int) -> np.ndarray:
        """EMA that handles leading NaN values."""
        alpha = 2.0 / (period + 1)
        result = np.full(len(data), np.nan)

        first_valid = None
        for i in range(len(data)):
            if not np.isnan(data[i]):
                first_valid = i
                break
        if first_valid is None:
            return result

        # Collect enough valid values for seed
        valid_vals = []
        seed_idx = first_valid
        for i in range(first_valid, len(data)):
            if not np.isnan(data[i]):
                valid_vals.append(data[i])
                if len(valid_vals) == period:
                    seed_idx = i
                    break

        if len(valid_vals) < period:
            return result

        result[seed_idx] = np.mean(valid_vals)
        for i in range(seed_idx + 1, len(data)):
            val = data[i] if not np.isnan(data[i]) else result[i - 1]
            result[i] = alpha * val + (1 - alpha) * result[i - 1]

        return result

    def _find_peaks(self, hist: np.ndarray) -> List[Tuple[int, float]]:
        """Find peaks (local maxima above zero) in MACD-H."""
        peaks = []
        lb = self.peak_lookback
        for i in range(lb, len(hist) - lb):
            if hist[i] <= 0:
                continue
            is_peak = True
            for j in range(1, lb + 1):
                if hist[i - j] >= hist[i] or hist[i + j] >= hist[i]:
                    is_peak = False
                    break
            if is_peak:
                peaks.append((i, float(hist[i])))
        return peaks

    def _find_troughs(self, hist: np.ndarray) -> List[Tuple[int, float]]:
        """Find troughs (local minima below zero) in MACD-H."""
        troughs = []
        lb = self.peak_lookback
        for i in range(lb, len(hist) - lb):
            if hist[i] >= 0:
                continue
            is_trough = True
            for j in range(1, lb + 1):
                if hist[i - j] <= hist[i] or hist[i + j] <= hist[i]:
                    is_trough = False
                    break
            if is_trough:
                troughs.append((i, float(hist[i])))
        return troughs

    def _has_zero_crossing(self, hist: np.ndarray, idx1: int, idx2: int) -> bool:
        """Check if MACD-H crosses zero between two indices (Elder's mandatory rule)."""
        if idx1 >= idx2:
            return False
        segment = hist[idx1:idx2 + 1]
        has_positive = np.any(segment > 0)
        has_negative = np.any(segment < 0)
        return has_positive and has_negative

    def _detect_divergences(
        self, hist: np.ndarray, high: np.ndarray, low: np.ndarray,
        close: np.ndarray, peaks: List[Tuple[int, float]],
        troughs: List[Tuple[int, float]]
    ) -> List[Dict[str, Any]]:
        """Detect bullish and bearish divergences with zero-line crossing validation."""
        divergences = []

        # Bearish divergence: price higher high + MACD-H lower peak
        for i in range(1, len(peaks)):
            idx1, val1 = peaks[i - 1]
            idx2, val2 = peaks[i]

            if val2 >= val1:
                continue  # Second peak must be lower

            # Check zero-line crossing between peaks
            if not self._has_zero_crossing(hist, idx1, idx2):
                continue

            # Check price made higher high
            price_high1 = np.max(high[max(0, idx1 - 2):idx1 + 3])
            price_high2 = np.max(high[max(0, idx2 - 2):idx2 + 3])

            if price_high2 > price_high1:
                strength = abs(val1 - val2) / abs(val1) if val1 != 0 else 0
                divergences.append({
                    'type': 'BEARISH',
                    'start_idx': idx1,
                    'end_idx': idx2,
                    'hist_start': val1,
                    'hist_end': val2,
                    'price_start': float(price_high1),
                    'price_end': float(price_high2),
                    'strength': min(strength, 1.0),
                })

        # Bullish divergence: price lower low + MACD-H higher trough
        for i in range(1, len(troughs)):
            idx1, val1 = troughs[i - 1]
            idx2, val2 = troughs[i]

            if val2 <= val1:
                continue  # Second trough must be higher (less negative)

            # Check zero-line crossing between troughs
            if not self._has_zero_crossing(hist, idx1, idx2):
                continue

            # Check price made lower low
            price_low1 = np.min(low[max(0, idx1 - 2):idx1 + 3])
            price_low2 = np.min(low[max(0, idx2 - 2):idx2 + 3])

            if price_low2 < price_low1:
                strength = abs(val2 - val1) / abs(val1) if val1 != 0 else 0
                divergences.append({
                    'type': 'BULLISH',
                    'start_idx': idx1,
                    'end_idx': idx2,
                    'hist_start': val1,
                    'hist_end': val2,
                    'price_start': float(price_low1),
                    'price_end': float(price_low2),
                    'strength': min(strength, 1.0),
                })

        # Sort by end_idx
        divergences.sort(key=lambda d: d['end_idx'])
        return divergences

    # --- Public getters ---

    def get_latest_divergence(self) -> Optional[Dict[str, Any]]:
        if not self.divergences:
            return None
        return self.divergences[-1]

    def get_all_divergences(self) -> List[Dict[str, Any]]:
        return self.divergences or []

    def has_active_divergence(self, lookback_bars: int = 10) -> Optional[str]:
        """Check if there's a recent divergence within lookback_bars of the end."""
        if not self.divergences or self.histogram is None:
            return None
        last_idx = len(self.histogram) - 1
        for div in reversed(self.divergences):
            if last_idx - div['end_idx'] <= lookback_bars:
                return div['type']
        return None

    def get_signal_summary(self) -> Dict[str, Any]:
        if self.histogram is None:
            return {'status': 'no_data'}

        latest_div = self.get_latest_divergence()
        active = self.has_active_divergence()

        return {
            'histogram': float(self.histogram[-1]),
            'total_divergences': len(self.divergences) if self.divergences else 0,
            'latest_divergence': latest_div,
            'active_divergence': active,
            'peaks_found': len(self.peaks) if self.peaks else 0,
            'troughs_found': len(self.troughs) if self.troughs else 0,
        }

    def get_required_data_points(self) -> int:
        return self.slow_length + self.signal_length + self.peak_lookback
