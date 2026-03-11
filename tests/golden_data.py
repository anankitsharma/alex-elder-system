"""
Golden Reference Dataset — Deterministic 50-bar OHLCV for indicator validation.

Layout:
  Bars  0-14: Uptrend   (close 100 → 114)
  Bars 15-24: Downtrend (close 114 → 105)
  Bars 25-34: Flat      (close ~105 ± 1)
  Bars 35-49: Strong uptrend (close 105 → 130)

Every value is a simple round number so hand-computation is feasible.
Volume follows a steady pattern (100k base + variation).
"""

import pandas as pd
import numpy as np

# fmt: off
GOLDEN_CLOSE = [
    100, 101, 102, 103, 104, 105, 106, 107, 108, 109,
    110, 111, 112, 113, 114,                              # bars 0-14: uptrend
    113, 112, 111, 110, 109, 108, 107, 106, 105.5, 105,  # bars 15-24: downtrend
    105, 105.5, 105, 104.5, 105, 105.5, 106, 105, 105.5, 105,  # bars 25-34: flat
    106, 108, 110, 112, 114, 116, 118, 120, 122, 124,
    126, 128, 129, 130, 131,                               # bars 35-49 (15 bars): strong uptrend
]

GOLDEN_HIGH = [
    101, 102, 103, 104, 105, 106, 107, 108, 109, 110,
    111, 112, 113, 114, 115,
    114, 113, 112, 111, 110, 109, 108, 107, 106.5, 106,
    106, 106.5, 106, 105.5, 106, 106.5, 107, 106, 106.5, 106,
    107, 109, 111, 113, 115, 117, 119, 121, 123, 125,
    127, 129, 130, 131, 132,
]

GOLDEN_LOW = [
    99, 100, 101, 102, 103, 104, 105, 106, 107, 108,
    109, 110, 111, 112, 113,
    112, 111, 110, 109, 108, 107, 106, 105, 104.5, 104,
    104, 104.5, 104, 103.5, 104, 104.5, 105, 104, 104.5, 104,
    105, 107, 109, 111, 113, 115, 117, 119, 121, 123,
    125, 127, 128, 129, 130,
]

GOLDEN_OPEN = [
    100, 100, 101, 102, 103, 104, 105, 106, 107, 108,
    109, 110, 111, 112, 113,
    114, 113, 112, 111, 110, 109, 108, 107, 106, 105.5,
    105, 105, 105.5, 105, 104.5, 105, 105.5, 106, 105, 105.5,
    105, 106, 108, 110, 112, 114, 116, 118, 120, 122,
    124, 126, 128, 129, 130,
]

GOLDEN_VOLUME = [
    100000, 110000, 105000, 120000, 115000, 130000, 125000, 140000, 135000, 150000,
    145000, 160000, 155000, 170000, 165000,
    180000, 175000, 190000, 185000, 200000, 195000, 210000, 205000, 180000, 170000,
    150000, 140000, 130000, 120000, 110000, 115000, 120000, 125000, 130000, 135000,
    160000, 180000, 200000, 220000, 240000, 260000, 280000, 300000, 320000, 340000,
    350000, 360000, 370000, 380000, 390000,
]
# fmt: on

assert len(GOLDEN_CLOSE) == 50
assert len(GOLDEN_HIGH) == 50
assert len(GOLDEN_LOW) == 50
assert len(GOLDEN_OPEN) == 50
assert len(GOLDEN_VOLUME) == 50


def get_golden_dataframe() -> pd.DataFrame:
    """Return the deterministic 50-bar OHLCV dataset as a DataFrame."""
    return pd.DataFrame({
        'datetime': pd.date_range('2024-01-01', periods=50, freq='D'),
        'open': GOLDEN_OPEN,
        'high': GOLDEN_HIGH,
        'low': GOLDEN_LOW,
        'close': GOLDEN_CLOSE,
        'volume': GOLDEN_VOLUME,
    })


def get_large_golden_dataframe(n: int = 2000) -> pd.DataFrame:
    """Return a large deterministic dataset by repeating/extending the golden data.
    Used for performance benchmarks."""
    base = get_golden_dataframe()
    repeats = (n // 50) + 1
    frames = []
    for i in range(repeats):
        chunk = base.copy()
        # Shift prices up slightly per repeat to avoid exact duplication
        offset = i * 30
        chunk['open'] = chunk['open'] + offset
        chunk['high'] = chunk['high'] + offset
        chunk['low'] = chunk['low'] + offset
        chunk['close'] = chunk['close'] + offset
        chunk['volume'] = chunk['volume'] + i * 10000
        chunk['datetime'] = pd.date_range(
            start=pd.Timestamp('2024-01-01') + pd.Timedelta(days=i * 50),
            periods=50, freq='D'
        )
        frames.append(chunk)
    result = pd.concat(frames, ignore_index=True).iloc[:n]
    return result


# ── Hand-computed expected EMA-13 values ──────────────────────────────
# SMA seed = mean(close[0:13]) = mean(100..112) = 106.0
# alpha = 2/(13+1) = 2/14 ≈ 0.142857142857

def compute_ema(data, period):
    """Hand-compute EMA for validation."""
    alpha = 2.0 / (period + 1)
    result = np.zeros(len(data))
    result[period - 1] = np.mean(data[:period])
    for i in range(period, len(data)):
        result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
    # Return from period-1 onward (first period-1 are zeros)
    return result[period - 1:]


EXPECTED_EMA13 = compute_ema(np.array(GOLDEN_CLOSE), 13)
EXPECTED_EMA22 = compute_ema(np.array(GOLDEN_CLOSE), 22)


def compute_macd(close_data, fast=12, slow=26, signal=9):
    """Hand-compute MACD line, signal, histogram."""
    close = np.array(close_data)

    # Full EMA arrays (with leading zeros)
    fast_full = np.zeros(len(close))
    fast_full[fast - 1] = np.mean(close[:fast])
    alpha_f = 2.0 / (fast + 1)
    for i in range(fast, len(close)):
        fast_full[i] = alpha_f * close[i] + (1 - alpha_f) * fast_full[i - 1]

    slow_full = np.zeros(len(close))
    slow_full[slow - 1] = np.mean(close[:slow])
    alpha_s = 2.0 / (slow + 1)
    for i in range(slow, len(close)):
        slow_full[i] = alpha_s * close[i] + (1 - alpha_s) * slow_full[i - 1]

    start = slow - 1  # index 25
    macd_line = fast_full[start:] - slow_full[start:]

    # Signal EMA on macd_line (starting from valid values, skip NaN/zero prefix)
    # The MACD code filters out NaN from the macd_line, but here all are valid from start
    # Signal uses SMA seed of first `signal` valid MACD values
    alpha_sig = 2.0 / (signal + 1)
    sig = np.full(len(macd_line), np.nan)
    sig[signal - 1] = np.mean(macd_line[:signal])
    for i in range(signal, len(macd_line)):
        sig[i] = alpha_sig * macd_line[i] + (1 - alpha_sig) * sig[i - 1]

    # Trim to where signal is valid
    valid_start = signal - 1
    aligned_macd = macd_line[valid_start:]
    aligned_signal = sig[valid_start:]
    histogram = aligned_macd - aligned_signal

    return aligned_macd, aligned_signal, histogram


EXPECTED_MACD_LINE, EXPECTED_MACD_SIGNAL, EXPECTED_MACD_HISTOGRAM = compute_macd(GOLDEN_CLOSE)
