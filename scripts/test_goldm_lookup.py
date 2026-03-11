"""Script: Look up GOLDM (Gold Mini) futures contract from Angel One scrip master.

Finds the best GOLDM futures contract (earliest expiry >= 7 days out)
and prints its token, trading symbol, lot size, and expiry.

Usage:
    cd backend && python ../scripts/test_goldm_lookup.py
"""

import sys
import json
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

from test_nifty_lookup import download_scrip_master

MINIMUM_DAYS_TO_EXPIRY = 7


def find_goldm_futures(data: list[dict]) -> list[dict]:
    """Find all GOLDM futures contracts from scrip master."""
    today = datetime.now()
    contracts = []

    for d in data:
        name = d.get("name", "")
        symbol = d.get("symbol", "")
        exch_seg = d.get("exch_seg", "")
        expiry_str = d.get("expiry")

        if name != "GOLDM" or exch_seg != "MCX" or "FUT" not in symbol:
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
    print("GOLDM (Gold Mini) Futures Contract Lookup")
    print("=" * 60)

    data = download_scrip_master()
    contracts = find_goldm_futures(data)

    print(f"\nFound {len(contracts)} GOLDM futures contracts:\n")
    print(f"{'Symbol':<30} {'Token':<10} {'Expiry':<12} {'Days Left':<10} {'Lot Size'}")
    print("-" * 80)
    best = find_best_contract(contracts)
    for c in contracts:
        marker = " <-- BEST" if c is best else ""
        print(f"{c['symbol']:<30} {c['token']:<10} {c['expiry_date']:<12} {c['days_left']:<10} {c['lot_size']}{marker}")

    if best:
        print(f"\nSelected contract:")
        print(f"  Symbol:     {best['symbol']}")
        print(f"  Token:      {best['token']}")
        print(f"  Exchange:   {best['exchange']}")
        print(f"  Expiry:     {best['expiry_date']} ({best['days_left']} days)")
        print(f"  Lot Size:   {best['lot_size']}")
        print(f"  Tick Size:  {best['tick_size']}")
    else:
        print("\nNo suitable GOLDM futures contract found!")

    # Also show other gold instruments on MCX
    print("\n" + "=" * 60)
    print("Other Gold instruments on MCX:")
    print("=" * 60)
    gold_mcx = [
        d for d in data
        if "GOLD" in d.get("name", "").upper()
        and d.get("exch_seg") == "MCX"
        and "FUT" in d.get("symbol", "")
    ]
    for d in gold_mcx[:15]:
        print(f"  {d.get('symbol', ''):<30} token={d.get('token', ''):<10} name={d.get('name', '')} expiry={d.get('expiry', '')}")


if __name__ == "__main__":
    main()
