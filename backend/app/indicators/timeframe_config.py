"""
Per-Timeframe Indicator Configuration

Maps Elder's Triple Screen system to specific indicators per screen
and timeframe mappings per asset class.

Screen 1 (Trend/Tide): Weekly — MACD-H slope, Impulse, EMA-13
Screen 2 (Oscillator/Wave): Daily — FI-2, FI-13, Elder-Ray, SafeZone, Value Zone, Impulse
Screen 3 (Precision Entry): Intraday — FI-2, SafeZone, trailing stops, Impulse
"""

from typing import Dict, List, Optional

# ── Which indicators to compute per screen ─────────────────────────────

SCREEN_INDICATOR_CONFIG: Dict[int, List[str]] = {
    1: [
        'ema13',
        'macd',
        'impulse',
    ],
    2: [
        'ema13',
        'ema22',
        'macd',
        'force_index_2',
        'force_index_13',
        'impulse',
        'elder_ray',
        'safezone',
        'value_zone',
        'elder_thermometer',
        'macd_divergence',
    ],
    3: [
        'ema13',
        'force_index_2',
        'impulse',
        'safezone',
    ],
}

# All indicators (when no screen specified)
ALL_INDICATORS = [
    'ema13', 'ema22', 'macd', 'force_index_2', 'force_index_13',
    'impulse', 'elder_ray', 'safezone', 'value_zone',
    'auto_envelope', 'elder_thermometer', 'macd_divergence',
]

# ── Asset class → timeframe mapping per screen ─────────────────────────

ASSET_TIMEFRAME_MAP: Dict[str, Dict[int, str]] = {
    'EQUITY': {1: '1w', 2: '1d', 3: '1h'},
    'INDEX_FO': {1: '1d', 2: '1h', 3: '15m'},
    'COMMODITY': {1: '1d', 2: '1h', 3: '15m'},
    'DEFAULT': {1: '1d', 2: '4h', 3: '1h'},
}

# ── Known index F&O symbols ────────────────────────────────────────────

INDEX_FO_SYMBOLS = {
    'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY',
    'NIFTY50', 'NIFTYNXT50',
}

COMMODITY_SYMBOLS = {
    'GOLDM', 'GOLD', 'SILVERM', 'SILVER', 'CRUDEOIL', 'NATURALGAS',
    'COPPER', 'ZINC', 'LEAD', 'ALUMINIUM', 'NICKEL',
}


def get_asset_class(symbol: str, exchange: str = 'NSE') -> str:
    """Determine asset class from symbol and exchange."""
    sym = symbol.upper()
    if sym in INDEX_FO_SYMBOLS:
        return 'INDEX_FO'
    if exchange.upper() == 'MCX' or sym in COMMODITY_SYMBOLS:
        return 'COMMODITY'
    if exchange.upper() in ('NSE', 'BSE', 'NFO'):
        return 'EQUITY'
    return 'DEFAULT'


def get_indicators_for_screen(screen: int) -> List[str]:
    """Get list of indicator names to compute for a given screen.

    Args:
        screen: 1, 2, or 3

    Returns:
        List of indicator identifiers
    """
    return SCREEN_INDICATOR_CONFIG.get(screen, ALL_INDICATORS)


def get_timeframe_for_screen(symbol: str, screen: int, exchange: str = 'NSE') -> str:
    """Get recommended timeframe for a given symbol and screen number.

    Args:
        symbol: Trading symbol (e.g. 'RELIANCE', 'NIFTY')
        screen: 1, 2, or 3
        exchange: Exchange code (NSE, NFO, MCX, etc.)

    Returns:
        Timeframe string (e.g. '1w', '1d', '1h', '15m')
    """
    asset_class = get_asset_class(symbol, exchange)
    mapping = ASSET_TIMEFRAME_MAP.get(asset_class, ASSET_TIMEFRAME_MAP['DEFAULT'])
    return mapping.get(screen, '1d')


def should_compute_indicator(indicator_name: str, screen: Optional[int]) -> bool:
    """Check if a specific indicator should be computed for the given screen.

    Args:
        indicator_name: Indicator identifier
        screen: Screen number (1, 2, 3) or None for all

    Returns:
        True if the indicator should be computed
    """
    if screen is None:
        return True
    indicators = get_indicators_for_screen(screen)
    return indicator_name in indicators
