"""Market hours configuration for Indian exchanges.

Handles exchange-specific trading sessions including MCX summer/winter
timing changes based on US DST (Daylight Saving Time).

MCX non-agri commodities follow US DST for their evening close:
  - Summer (US DST active, ~2nd Sun Mar to 1st Sun Nov): close 23:30 IST
  - Winter (US Standard Time): close 23:55 IST

Reference: MCX circular, confirmed against Zerodha/Angel One docs.
"""

from datetime import datetime, time as dt_time, date
from typing import Optional

import pytz

IST = pytz.timezone("Asia/Kolkata")
US_EASTERN = pytz.timezone("US/Eastern")

# ── MCX commodity classification ─────────────────────────────

# Category A: Domestic agri — 9:00–17:00 IST (year-round)
MCX_AGRI_SYMBOLS = frozenset({
    "COTTON", "COTTONCANDY", "CPO", "KAPAS",
    "MENTHAOIL", "CASTORSEED", "PEPPER",
    "CARDAMOM", "RUBBER", "TURMERIC", "JEERA",
    "GUARGUM", "GUARSEEDS", "DHANIYA",
})

# Category B: International agri — 9:00–21:00 IST (year-round)
MCX_INTL_AGRI_SYMBOLS = frozenset({
    "COCUD", "COCUM", "SOYDEX", "RMSEED",
})

MCX_NON_AGRI_SYMBOLS = frozenset({
    "GOLD", "GOLDM", "GOLDGUINEA", "GOLDPETAL", "GOLDPETALDEL",
    "SILVER", "SILVERM", "SILVERMIC",
    "CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI",
    "COPPER", "COPPERM",
    "ZINC", "ZINCMINI",
    "LEAD", "LEADMINI",
    "ALUMINIUM", "ALUMINI",
    "NICKEL", "NICKELM",
})


# ── Session definitions ──────────────────────────────────────

class MarketSession:
    """Defines open/close times for a market segment."""

    def __init__(
        self,
        name: str,
        open_time: dt_time,
        close_time: dt_time,
        eod_cutoff_minutes: int = 5,
    ):
        self.name = name
        self.open_time = open_time
        self.close_time = close_time
        self.eod_cutoff_minutes = eod_cutoff_minutes

    def is_open(self, dt: datetime) -> bool:
        """Check if the market is open at the given datetime."""
        if dt.tzinfo is None:
            dt = IST.localize(dt)
        else:
            dt = dt.astimezone(IST)
        t = dt.time()

        # Handle overnight sessions (MCX: open 9:00, close 23:30/23:55)
        if self.close_time < self.open_time:
            # Overnight: open from open_time to midnight, midnight to close_time
            return t >= self.open_time or t <= self.close_time
        else:
            return self.open_time <= t <= self.close_time

    def eod_cutoff_time(self) -> dt_time:
        """Returns the time at which EOD exit should be triggered."""
        close_minutes = self.close_time.hour * 60 + self.close_time.minute
        cutoff_minutes = close_minutes - self.eod_cutoff_minutes
        if cutoff_minutes < 0:
            cutoff_minutes += 24 * 60
        return dt_time(cutoff_minutes // 60, cutoff_minutes % 60)

    def __repr__(self):
        return f"MarketSession({self.name}, {self.open_time}-{self.close_time})"


# Pre-defined sessions
NSE_EQUITY = MarketSession("NSE_EQUITY", dt_time(9, 15), dt_time(15, 30), eod_cutoff_minutes=5)
NSE_FO = MarketSession("NSE_FO", dt_time(9, 15), dt_time(15, 30), eod_cutoff_minutes=5)
MCX_INTL_AGRI = MarketSession("MCX_INTL_AGRI", dt_time(9, 0), dt_time(21, 0), eod_cutoff_minutes=5)
NSE_CURRENCY = MarketSession("NSE_CURRENCY", dt_time(9, 0), dt_time(17, 0), eod_cutoff_minutes=5)
MCX_AGRI = MarketSession("MCX_AGRI", dt_time(9, 0), dt_time(17, 0), eod_cutoff_minutes=5)
MCX_NON_AGRI_SUMMER = MarketSession("MCX_NON_AGRI_SUMMER", dt_time(9, 0), dt_time(23, 30), eod_cutoff_minutes=5)
MCX_NON_AGRI_WINTER = MarketSession("MCX_NON_AGRI_WINTER", dt_time(9, 0), dt_time(23, 55), eod_cutoff_minutes=5)


def is_us_dst(dt: Optional[datetime] = None) -> bool:
    """Check if US Eastern is currently in DST (summer time).

    US DST: 2nd Sunday of March to 1st Sunday of November.
    When US DST is active -> MCX uses summer timings (close 23:30 IST).
    When US Standard Time -> MCX uses winter timings (close 23:55 IST).
    """
    if dt is None:
        dt = datetime.now(IST)

    # Convert to US/Eastern and check if DST is active
    us_dt = dt.astimezone(US_EASTERN)
    return bool(us_dt.dst())


def get_session(exchange: str, symbol: str = "", dt: Optional[datetime] = None) -> MarketSession:
    """Get the appropriate market session for an exchange/symbol.

    Args:
        exchange: Exchange code (NSE, BSE, NFO, BFO, CDS, MCX)
        symbol: Trading symbol (needed for MCX agri/non-agri classification)
        dt: Optional datetime for DST check (defaults to now)

    Returns:
        MarketSession with correct open/close times
    """
    exchange_upper = exchange.upper()

    if exchange_upper in ("NSE", "BSE"):
        return NSE_EQUITY
    elif exchange_upper in ("NFO", "BFO"):
        return NSE_FO
    elif exchange_upper in ("CDS", "BCD"):
        return NSE_CURRENCY
    elif exchange_upper == "MCX":
        # Classify by symbol
        sym_upper = symbol.upper().rstrip("0123456789").rstrip("-")
        # Strip month/expiry suffix for matching (e.g., GOLDM24MARFUT -> GOLDM)
        base_symbol = sym_upper.split("FUT")[0].split("OPT")[0]
        for s in sorted(MCX_AGRI_SYMBOLS, key=len, reverse=True):
            if base_symbol.startswith(s):
                return MCX_AGRI
        for s in sorted(MCX_INTL_AGRI_SYMBOLS, key=len, reverse=True):
            if base_symbol.startswith(s):
                return MCX_INTL_AGRI

        # Default to non-agri (Gold, Silver, Crude, etc.)
        if is_us_dst(dt):
            return MCX_NON_AGRI_SUMMER
        else:
            return MCX_NON_AGRI_WINTER
    else:
        # Default to NSE equity hours
        return NSE_EQUITY


def is_market_open(exchange: str, symbol: str = "", dt: Optional[datetime] = None) -> bool:
    """Check if the market is currently open for the given exchange/symbol."""
    if dt is None:
        dt = datetime.now(IST)
    session = get_session(exchange, symbol, dt)
    # Also check for weekends
    weekday = dt.astimezone(IST).weekday()
    if weekday >= 5:  # Saturday=5, Sunday=6
        return False
    return session.is_open(dt)


def get_eod_cutoff(exchange: str, symbol: str = "", dt: Optional[datetime] = None) -> dt_time:
    """Get the EOD auto-close cutoff time for the given exchange/symbol."""
    session = get_session(exchange, symbol, dt)
    return session.eod_cutoff_time()


def get_close_time(exchange: str, symbol: str = "", dt: Optional[datetime] = None) -> dt_time:
    """Get the market close time for the given exchange/symbol."""
    session = get_session(exchange, symbol, dt)
    return session.close_time
