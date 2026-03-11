"""Script 2: Fetch NIFTY historical candle data from Angel One.

Authenticates with Angel One, looks up the NIFTY futures token,
and fetches daily/hourly/15m candles. Prints sample data and stats.

Usage:
    cd backend && python ../scripts/test_nifty_historical.py

Requires .env with Angel One credentials at project root.
"""

import sys
import os
import json
import time
from pathlib import Path
from datetime import datetime, timedelta

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# Load env before importing app modules
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


def main():
    print("=" * 60)
    print("NIFTY Historical Data Fetch Test")
    print("=" * 60)

    # Step 1: Find NIFTY contract
    sys.path.insert(0, str(SCRIPT_DIR))
    from test_nifty_lookup import download_scrip_master, find_nifty_futures, find_best_contract

    data = download_scrip_master()
    contracts = find_nifty_futures(data)
    best = find_best_contract(contracts)

    if not best:
        print("ERROR: No suitable NIFTY futures contract found!")
        return

    token = best["token"]
    symbol = best["symbol"]
    exchange = best["exchange"]
    print(f"\nUsing contract: {symbol} (token={token}, exchange={exchange})")

    # Step 2: Login to Angel One historical API
    print("\nLogging in to Angel One historical API...")
    from app.broker.angel_client import angel

    try:
        result = angel.login_historical()
        if not result.get("status"):
            print(f"Login failed: {result.get('message', 'Unknown error')}")
            print("Check your .env credentials (ANGEL_HIST_API_KEY, ANGEL_HIST_API_SECRET, etc.)")
            return
        print("Login successful!")
    except Exception as e:
        print(f"Login exception: {e}")
        return

    # Step 3: Fetch candles for each interval
    from app.broker.historical import fetch_historical_candles, INTERVAL_MAP

    intervals_to_test = [
        ("1d", 365, "Daily candles (1 year)"),
        ("1h", 60, "Hourly candles (60 days)"),
        ("15m", 30, "15-min candles (30 days)"),
    ]

    for interval, days, label in intervals_to_test:
        print(f"\n{'-' * 50}")
        print(f"Fetching {label}...")
        print(f"  Token: {token}, Exchange: {exchange}, Interval: {interval}")
        print(f"  Period: last {days} days")

        from_date = datetime.now() - timedelta(days=days)
        to_date = datetime.now()

        try:
            df = fetch_historical_candles(
                symbol_token=str(token),
                exchange=exchange,
                interval=interval,
                from_date=from_date,
                to_date=to_date,
            )
        except Exception as e:
            print(f"  ERROR: {e}")
            time.sleep(1)  # Rate limit
            continue

        if df.empty:
            print(f"  No data returned!")
            time.sleep(1)
            continue

        print(f"  Rows: {len(df)}")
        print(f"  Date range: {df['timestamp'].iloc[0]} -> {df['timestamp'].iloc[-1]}")
        print(f"  Price range: {df['low'].min():.2f} -- {df['high'].max():.2f}")
        print(f"  Latest close: {df['close'].iloc[-1]:.2f}")
        print(f"  Avg volume: {df['volume'].mean():.0f}")
        print(f"\n  First 3 candles:")
        for _, row in df.head(3).iterrows():
            print(f"    {row['timestamp']}  O={row['open']:.2f} H={row['high']:.2f} "
                  f"L={row['low']:.2f} C={row['close']:.2f} V={row['volume']}")
        print(f"  Last 3 candles:")
        for _, row in df.tail(3).iterrows():
            print(f"    {row['timestamp']}  O={row['open']:.2f} H={row['high']:.2f} "
                  f"L={row['low']:.2f} C={row['close']:.2f} V={row['volume']}")

        # Save to CSV for inspection
        csv_path = SCRIPT_DIR / f"nifty_{interval}.csv"
        df.to_csv(csv_path, index=False)
        print(f"  Saved to {csv_path}")

        time.sleep(1)  # Rate limit between requests

    print(f"\n{'=' * 60}")
    print("Done! Check the CSV files in scripts/ for full data.")


if __name__ == "__main__":
    main()
