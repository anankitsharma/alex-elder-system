"""
Cross-Timeframe Signal Validator

Enforces Elder's cross-timeframe rules:
1. Never trade against Screen 1 impulse (RED = no buys)
2. Screen 2 must align with Screen 1 tide
3. Impulse conflict detection across screens
4. Data timeframe verification
"""

import pandas as pd
from typing import Dict, Any, List, Optional
from loguru import logger


class ValidationResult:
    """Result of a cross-timeframe validation check."""

    def __init__(self, is_valid: bool, warnings: List[str] = None, blocks: List[str] = None):
        self.is_valid = is_valid
        self.warnings = warnings or []
        self.blocks = blocks or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            'is_valid': self.is_valid,
            'warnings': self.warnings,
            'blocks': self.blocks,
        }


def validate_screen_alignment(
    screen1_result: Dict[str, Any],
    screen2_result: Dict[str, Any],
) -> ValidationResult:
    """
    Validate that Screen 2 signals align with Screen 1 tide.

    Rules:
    - Bullish tide → only BUY signals allowed on Screen 2
    - Bearish tide → only SELL signals allowed on Screen 2
    - Neutral tide → no signals allowed (wait)

    Args:
        screen1_result: Output of _screen1_trend()
        screen2_result: Output of _screen2_oscillator()

    Returns:
        ValidationResult with warnings/blocks
    """
    warnings = []
    blocks = []
    is_valid = True

    tide = screen1_result.get('tide', 'NEUTRAL')
    signal = screen2_result.get('signal', 'NONE')
    s1_impulse = screen1_result.get('impulse_signal', 'neutral')

    # Rule 1: Never trade against Screen 1 RED impulse
    if s1_impulse == 'bearish' and signal == 'BUY':
        blocks.append(
            "BLOCKED: Screen 1 impulse is RED — no BUY signals allowed"
        )
        is_valid = False

    if s1_impulse == 'bullish' and signal == 'SELL':
        blocks.append(
            "BLOCKED: Screen 1 impulse is GREEN — no SELL signals allowed"
        )
        is_valid = False

    # Rule 2: Tide/signal alignment
    if tide == 'BULLISH' and signal == 'SELL':
        blocks.append(
            f"BLOCKED: Tide is {tide} but Screen 2 signal is {signal}"
        )
        is_valid = False

    if tide == 'BEARISH' and signal == 'BUY':
        blocks.append(
            f"BLOCKED: Tide is {tide} but Screen 2 signal is {signal}"
        )
        is_valid = False

    if tide == 'NEUTRAL' and signal != 'NONE':
        warnings.append(
            f"WARNING: Tide is NEUTRAL — {signal} signal is unreliable"
        )

    return ValidationResult(is_valid=is_valid, warnings=warnings, blocks=blocks)


def validate_impulse_consistency(
    impulses: Dict[str, str],
) -> ValidationResult:
    """
    Check for impulse conflicts across timeframes.

    Args:
        impulses: Dict of timeframe -> impulse signal
            e.g. {'screen1': 'bullish', 'screen2': 'bearish'}

    Returns:
        ValidationResult with conflict warnings
    """
    warnings = []
    blocks = []
    is_valid = True

    values = list(impulses.values())
    has_bullish = 'bullish' in values
    has_bearish = 'bearish' in values

    if has_bullish and has_bearish:
        conflicting = [f"{k}={v}" for k, v in impulses.items() if v in ('bullish', 'bearish')]
        warnings.append(
            f"CONFLICT: Impulse signals disagree across screens: {', '.join(conflicting)}. "
            "Consider waiting for alignment."
        )
        # Not a hard block, but a warning
        is_valid = True

    # Screen 1 RED is a hard block for buys
    s1_impulse = impulses.get('screen1', 'neutral')
    s2_impulse = impulses.get('screen2', 'neutral')

    if s1_impulse == 'bearish' and s2_impulse == 'bullish':
        blocks.append(
            "BLOCKED: Screen 1 bearish impulse overrides Screen 2 bullish impulse"
        )
        is_valid = False

    if s1_impulse == 'bullish' and s2_impulse == 'bearish':
        blocks.append(
            "BLOCKED: Screen 1 bullish impulse overrides Screen 2 bearish impulse"
        )
        is_valid = False

    return ValidationResult(is_valid=is_valid, warnings=warnings, blocks=blocks)


def validate_data_timeframe(data: pd.DataFrame, expected_tf: str) -> bool:
    """
    Verify that data resolution matches the expected timeframe.

    Checks the median time delta between consecutive bars to ensure
    it's consistent with the expected timeframe.

    Args:
        data: DataFrame with 'datetime' column
        expected_tf: Expected timeframe string (e.g. '1d', '1h', '15m', '1w')

    Returns:
        True if data resolution matches expected timeframe
    """
    if data is None or len(data) < 3:
        return True  # Can't verify with too little data

    try:
        dt_col = data['datetime']
        if not hasattr(dt_col.iloc[0], 'timestamp'):
            # Not datetime objects, can't verify
            return True

        deltas = pd.Series(dt_col).diff().dropna()
        median_delta = deltas.median()

        # Expected ranges per timeframe
        tf_ranges = {
            '1m': (pd.Timedelta(seconds=30), pd.Timedelta(minutes=3)),
            '5m': (pd.Timedelta(minutes=3), pd.Timedelta(minutes=10)),
            '15m': (pd.Timedelta(minutes=10), pd.Timedelta(minutes=30)),
            '1h': (pd.Timedelta(minutes=30), pd.Timedelta(hours=3)),
            '4h': (pd.Timedelta(hours=2), pd.Timedelta(hours=8)),
            '1d': (pd.Timedelta(hours=12), pd.Timedelta(days=3)),
            '1w': (pd.Timedelta(days=4), pd.Timedelta(days=10)),
        }

        if expected_tf not in tf_ranges:
            logger.debug(f"Unknown timeframe '{expected_tf}', skipping validation")
            return True

        min_delta, max_delta = tf_ranges[expected_tf]
        is_valid = min_delta <= median_delta <= max_delta

        if not is_valid:
            logger.warning(
                f"Data timeframe mismatch: expected {expected_tf}, "
                f"median delta is {median_delta}"
            )

        return is_valid

    except Exception as e:
        logger.debug(f"Could not verify data timeframe: {e}")
        return True  # Don't block on verification failure


def validate_full_analysis(
    screen1_result: Dict[str, Any],
    screen2_result: Dict[str, Any],
    screen3_result: Optional[Dict[str, Any]] = None,
) -> ValidationResult:
    """
    Run all cross-timeframe validations and combine results.

    Args:
        screen1_result: Screen 1 analysis output
        screen2_result: Screen 2 analysis output
        screen3_result: Optional Screen 3 analysis output

    Returns:
        Combined ValidationResult
    """
    all_warnings = []
    all_blocks = []

    # Alignment validation
    alignment = validate_screen_alignment(screen1_result, screen2_result)
    all_warnings.extend(alignment.warnings)
    all_blocks.extend(alignment.blocks)

    # Impulse consistency
    impulses = {
        'screen1': screen1_result.get('impulse_signal', 'neutral'),
        'screen2': screen2_result.get('impulse_signal', 'neutral'),
    }
    impulse_check = validate_impulse_consistency(impulses)
    all_warnings.extend(impulse_check.warnings)
    all_blocks.extend(impulse_check.blocks)

    is_valid = len(all_blocks) == 0
    return ValidationResult(is_valid=is_valid, warnings=all_warnings, blocks=all_blocks)
