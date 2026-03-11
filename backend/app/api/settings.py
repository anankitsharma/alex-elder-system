"""Settings API — persistent configuration backed by a JSON file."""

import json
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings as app_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])

SETTINGS_FILE = Path(__file__).resolve().parents[2] / "data" / "settings.json"

# ── Defaults ──────────────────────────────────────────────────────

DEFAULTS: Dict[str, Any] = {
    "watchlist": [
        {"symbol": "NIFTY", "exchange": "NFO"},
        {"symbol": "RELIANCE", "exchange": "NSE"},
        {"symbol": "HDFCBANK", "exchange": "NSE"},
        {"symbol": "INFY", "exchange": "NSE"},
        {"symbol": "TCS", "exchange": "NSE"},
        {"symbol": "SBIN", "exchange": "NSE"},
        {"symbol": "ITC", "exchange": "NSE"},
    ],
    "timeframes": {
        "EQUITY":    {"screen1": "1w", "screen2": "1d", "screen3": "1h"},
        "INDEX_FO":  {"screen1": "1d", "screen2": "1h", "screen3": "15m"},
        "COMMODITY": {"screen1": "1d", "screen2": "1h", "screen3": "15m"},
        "DEFAULT":   {"screen1": "1d", "screen2": "4h", "screen3": "1h"},
    },
    "risk": {
        "max_risk_per_trade_pct": app_settings.max_risk_per_trade_pct,
        "max_portfolio_risk_pct": app_settings.max_portfolio_risk_pct,
        "min_signal_score": app_settings.min_signal_score,
    },
    "display": {
        "default_symbol": "NIFTY",
        "default_exchange": "NFO",
        "default_interval": "1d",
        "show_volume": True,
        "show_macd": True,
        "show_force_index": True,
        "show_elder_ray": True,
    },
}

# ── In-memory store ───────────────────────────────────────────────

_store: Dict[str, Any] = {}


def _load() -> None:
    global _store
    if SETTINGS_FILE.exists():
        try:
            _store = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            _store = {}
    # Fill in any missing keys from defaults
    for key, default in DEFAULTS.items():
        if key not in _store:
            _store[key] = default


def _save() -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(_store, indent=2), encoding="utf-8")


_load()


# ── Models ────────────────────────────────────────────────────────

class SettingValue(BaseModel):
    value: Any


class WatchlistItem(BaseModel):
    symbol: str
    exchange: str = "NSE"


# ── CRUD endpoints ────────────────────────────────────────────────

@router.get("")
async def get_all_settings():
    """Return all settings."""
    return _store


@router.get("/{key}")
async def get_setting(key: str):
    """Return a single setting by key."""
    if key not in _store:
        return {"error": f"Unknown key: {key}"}
    return {key: _store[key]}


@router.put("/{key}")
async def update_setting(key: str, body: SettingValue):
    """Update a single setting by key."""
    _store[key] = body.value
    _save()
    return {"status": True, "key": key, "value": body.value}


# ── Watchlist shortcuts ───────────────────────────────────────────

@router.post("/watchlist/add")
async def add_to_watchlist(item: WatchlistItem):
    """Add a symbol to the watchlist."""
    wl: List[Dict[str, str]] = _store.get("watchlist", [])
    if any(w["symbol"] == item.symbol and w["exchange"] == item.exchange for w in wl):
        return {"status": False, "message": "Already in watchlist", "watchlist": wl}
    wl.append({"symbol": item.symbol, "exchange": item.exchange})
    _store["watchlist"] = wl
    _save()
    return {"status": True, "watchlist": wl}


@router.post("/watchlist/remove")
async def remove_from_watchlist(item: WatchlistItem):
    """Remove a symbol from the watchlist."""
    wl: List[Dict[str, str]] = _store.get("watchlist", [])
    wl = [w for w in wl if not (w["symbol"] == item.symbol and w["exchange"] == item.exchange)]
    _store["watchlist"] = wl
    _save()
    return {"status": True, "watchlist": wl}
