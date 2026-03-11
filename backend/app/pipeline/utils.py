"""Shared pipeline utility functions.

Extracted from api/strategy.py for reuse in pipeline components.
"""

from typing import Any


def last_non_null(arr: list, default: Any = 0) -> Any:
    """Get last non-null value from an array."""
    if not arr:
        return default
    for v in reversed(arr):
        if v is not None:
            return v
    return default


def slope_of_last(arr: list, n: int = 3) -> float:
    """Get slope of last n non-null values."""
    vals = [v for v in arr if v is not None]
    if len(vals) < 2:
        return 0
    recent = vals[-min(n, len(vals)):]
    return recent[-1] - recent[0]


def trend_of_last(arr: list, n: int = 3) -> str:
    """Determine if last n values are RISING, FALLING, or FLAT."""
    vals = [v for v in arr if v is not None]
    if len(vals) < 2:
        return "UNKNOWN"
    recent = vals[-min(n, len(vals)):]
    diff = recent[-1] - recent[0]
    if diff > 0:
        return "RISING"
    elif diff < 0:
        return "FALLING"
    return "FLAT"
