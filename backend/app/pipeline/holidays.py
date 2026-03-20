"""Indian market holiday calendar for NSE, BSE, and MCX.

Used by:
- EOD auto-close: skip on holidays
- Gap detection: account for holiday gaps in candle data
- Market hours: is_trading_day() check

Holidays are hardcoded for 2025-2026. Add new years as needed.
"""

from datetime import date
from typing import Optional

from loguru import logger


# NSE/BSE holidays (2025-2026) — excludes weekends (handled separately)
_NSE_HOLIDAYS: set[date] = {
    # 2025
    date(2025, 1, 26),   # Republic Day
    date(2025, 2, 26),   # Maha Shivaratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-Ul-Fitr (Eid)
    date(2025, 4, 10),   # Mahavir Jayanti
    date(2025, 4, 14),   # Dr. Ambedkar Jayanti
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 6, 7),    # Bakri Id
    date(2025, 7, 6),    # Moharram
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 16),   # Parsi New Year
    date(2025, 9, 5),    # Milad un-Nabi
    date(2025, 10, 2),   # Mahatma Gandhi Jayanti / Dussehra
    date(2025, 10, 21),  # Diwali (Laxmi Pujan)
    date(2025, 10, 22),  # Diwali Balipratipada
    date(2025, 11, 5),   # Guru Nanak Jayanti
    date(2025, 11, 26),  # Constitution Day (market closed)
    date(2025, 12, 25),  # Christmas
    # 2026
    date(2026, 1, 26),   # Republic Day
    date(2026, 2, 17),   # Maha Shivaratri
    date(2026, 3, 3),    # Holi
    date(2026, 3, 20),   # Id-Ul-Fitr (Eid)
    date(2026, 3, 30),   # Mahavir Jayanti / Ram Navami
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 5, 27),   # Bakri Id
    date(2026, 6, 25),   # Moharram
    date(2026, 8, 15),   # Independence Day
    date(2026, 8, 25),   # Milad un-Nabi
    date(2026, 10, 2),   # Mahatma Gandhi Jayanti
    date(2026, 10, 12),  # Dussehra
    date(2026, 11, 9),   # Diwali (Laxmi Pujan)
    date(2026, 11, 10),  # Diwali Balipratipada
    date(2026, 11, 25),  # Guru Nanak Jayanti
    date(2026, 12, 25),  # Christmas
}

# MCX follows NSE holidays mostly, with a few additions
_MCX_EXTRA_HOLIDAYS: set[date] = set()  # Add MCX-specific holidays here

_MCX_HOLIDAYS = _NSE_HOLIDAYS | _MCX_EXTRA_HOLIDAYS


def is_holiday(dt: Optional[date] = None, exchange: str = "NSE") -> bool:
    """Check if a given date is a market holiday.

    Args:
        dt: Date to check. Defaults to today.
        exchange: NSE, BSE, or MCX.
    """
    if dt is None:
        dt = date.today()

    # Weekends are always holidays
    if dt.weekday() >= 5:
        return True

    if exchange in ("MCX",):
        return dt in _MCX_HOLIDAYS
    return dt in _NSE_HOLIDAYS


def is_trading_day(dt: Optional[date] = None, exchange: str = "NSE") -> bool:
    """Check if a given date is a trading day (not weekend, not holiday)."""
    return not is_holiday(dt, exchange)


def next_trading_day(dt: Optional[date] = None, exchange: str = "NSE") -> date:
    """Find the next trading day after the given date."""
    from datetime import timedelta
    if dt is None:
        dt = date.today()
    dt = dt + timedelta(days=1)
    while is_holiday(dt, exchange):
        dt += timedelta(days=1)
    return dt


def holidays_between(start: date, end: date, exchange: str = "NSE") -> int:
    """Count number of holidays (weekends + market holidays) between two dates."""
    count = 0
    from datetime import timedelta
    current = start + timedelta(days=1)
    while current < end:
        if is_holiday(current, exchange):
            count += 1
        current += timedelta(days=1)
    return count
