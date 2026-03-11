"""Script 1: Look up NIFTY futures contract from Angel One scrip master.

Finds the best NIFTY futures contract (earliest expiry >= 7 days out)
and prints its token, trading symbol, lot size, and expiry.

Usage:
    cd backend && python -m scripts.test_nifty_lookup
    OR
    cd backend && python ../scripts/test_nifty_lookup.py
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime

# Add backend to path so we can import app modules
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import httpx

SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
CACHE_FILE = BACKEND_DIR / "data" / "scrip_master.json"
MINIMUM_DAYS_TO_EXPIRY = 7


def download_scrip_master() -> list[dict]:
    """Download or load cached scrip master."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

    if CACHE_FILE.exists():
        mtime = datetime.fromtimestamp(CACHE_FILE.stat().st_mtime)
        if mtime.date() == datetime.now().date():
            print(f"Using cached scrip master from {mtime.strftime('%Y-%m-%d %H:%M')}")
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))

    print("Downloading scrip master from Angel One (~30MB)...")
    resp = httpx.get(SCRIP_MASTER_URL, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    CACHE_FILE.write_text(json.dumps(data), encoding="utf-8")
    print(f"Downloaded {len(data)} instruments")
    return data


def find_nifty_futures(data: list[dict]) -> list[dict]:
    """Find all NIFTY futures contracts from scrip master."""
    today = datetime.now()
    contracts = []

    for d in data:
        name = d.get("name", "")
        symbol = d.get("symbol", "")
        exch_seg = d.get("exch_seg", "")
        expiry_str = d.get("expiry")

        if name != "NIFTY" or exch_seg != "NFO" or "FUT" not in symbol:
            continue
        if not expiry_str:
            continue

        try:
            expiry_date = datetime.strptime(expiry_str, "%d%b%Y")
        except ValueError:
            continue

        days_left = (expiry_date - today).days
        lot_size = int(float(d.get("lotsize", 0) or 0))

        contracts.append({
            "name": name,
            "symbol": symbol,
            "token": d["token"],
            "exchange": exch_seg,
            "expiry": expiry_str,
            "expiry_date": expiry_date.strftime("%Y-%m-%d"),
            "days_left": days_left,
            "lot_size": lot_size,
            "tick_size": d.get("tick_size"),
        })

    contracts.sort(key=lambda x: x["days_left"])
    return contracts


def find_best_contract(contracts: list[dict]) -> dict | None:
    """Select the best contract: earliest expiry >= MINIMUM_DAYS_TO_EXPIRY."""
    return next(
        (c for c in contracts if c["days_left"] >= MINIMUM_DAYS_TO_EXPIRY),
        None,
    )


def main():
    print("=" * 60)
    print("NIFTY Futures Contract Lookup")
    print("=" * 60)

    data = download_scrip_master()
    contracts = find_nifty_futures(data)

    print(f"\nFound {len(contracts)} NIFTY futures contracts:\n")
    print(f"{'Symbol':<25} {'Token':<10} {'Expiry':<12} {'Days Left':<10} {'Lot Size'}")
    print("-" * 75)
    for c in contracts:
        marker = " <-- BEST" if c["days_left"] >= MINIMUM_DAYS_TO_EXPIRY else " (too close)"
        if c == find_best_contract(contracts):
            marker = " <-- BEST"
        print(f"{c['symbol']:<25} {c['token']:<10} {c['expiry_date']:<12} {c['days_left']:<10} {c['lot_size']}{marker}")

    best = find_best_contract(contracts)
    if best:
        print(f"\nSelected contract:")
        print(f"  Symbol:     {best['symbol']}")
        print(f"  Token:      {best['token']}")
        print(f"  Exchange:   {best['exchange']}")
        print(f"  Expiry:     {best['expiry_date']} ({best['days_left']} days)")
        print(f"  Lot Size:   {best['lot_size']}")
        print(f"  Tick Size:  {best['tick_size']}")
    else:
        print("\nNo suitable NIFTY futures contract found!")

    # Also look for NIFTY spot (NSE index)
    print("\n" + "=" * 60)
    print("NIFTY Spot / Index entries in NSE:")
    print("=" * 60)
    nifty_nse = [
        d for d in data
        if "NIFTY" in d.get("name", "").upper()
        and d.get("exch_seg") == "NSE"
    ]
    for d in nifty_nse[:10]:
        print(f"  {d.get('symbol', ''):<20} token={d.get('token', ''):<10} name={d.get('name', '')}")

    if not nifty_nse:
        print("  (no NSE NIFTY entries found — index data may be on NFO exchange only)")


if __name__ == "__main__":
    main()
