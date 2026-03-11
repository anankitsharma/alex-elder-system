"""Script: Fill GOLDM historical data into DB and verify via API.

Authenticates, fetches GOLDM data for all 3 screen timeframes,
persists to SQLite, and verifies the API endpoints work.

Usage:
    cd backend && python ../scripts/test_goldm_pipeline.py

Requires:
  - .env with Angel One credentials
  - Backend running on port 8000 (for API verification step)
"""

import sys
import time
import asyncio
from pathlib import Path
from datetime import datetime, timedelta

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


async def fill_goldm_data():
    """Fetch GOLDM historical data and persist to database."""
    print("=" * 60)
    print("GOLDM Data Pipeline -- Fetch + Store + Verify")
    print("=" * 60)

    # Step 1: Find GOLDM contract
    from test_goldm_lookup import find_goldm_futures, find_best_contract
    from test_nifty_lookup import download_scrip_master

    data = download_scrip_master()
    contracts = find_goldm_futures(data)
    best = find_best_contract(contracts)

    if not best:
        print("ERROR: No suitable GOLDM futures contract found!")
        return

    token = str(best["token"])
    symbol = best["symbol"]
    name = "GOLDM"
    exchange = best["exchange"]
    lot_size = best["lot_size"]
    print(f"\nContract: {symbol} (token={token}, exchange={exchange}, lot={lot_size})")

    # Step 2: Login to Angel One
    print("\nLogging in to Angel One...")
    from app.broker.angel_client import angel

    try:
        result = angel.login_historical()
        if not result.get("status"):
            print(f"Login failed: {result.get('message')}")
            return
        print("Login OK")
    except Exception as e:
        print(f"Login error: {e}")
        return

    # Step 3: Fetch candle data (COMMODITY asset class: 1d/1h/15m)
    from app.broker.historical import fetch_historical_candles

    timeframes = {
        "1d": 365,
        "1h": 60,
        "15m": 30,
    }

    candle_data = {}
    for tf, days in timeframes.items():
        print(f"\nFetching {tf} candles ({days} days)...")
        df = fetch_historical_candles(
            symbol_token=token,
            exchange=exchange,
            interval=tf,
            from_date=datetime.now() - timedelta(days=days),
            to_date=datetime.now(),
        )
        if df.empty:
            print(f"  WARNING: No {tf} data returned")
        else:
            print(f"  Got {len(df)} candles: {df['timestamp'].iloc[0]} -> {df['timestamp'].iloc[-1]}")
            candle_data[tf] = df
        time.sleep(1)

    if not candle_data:
        print("\nERROR: No candle data fetched at all!")
        return

    # Step 4: Persist to database
    print(f"\n{'-' * 50}")
    print("Persisting to database...")

    from app.database import async_session, init_db
    from app.pipeline.db_persistence import get_or_create_instrument, save_candles

    await init_db()

    async with async_session() as session:
        instrument = await get_or_create_instrument(
            session=session,
            symbol=symbol,
            exchange=exchange,
            token=token,
            name=name,
        )
        print(f"  Instrument: id={instrument.id}, symbol={instrument.symbol}, exchange={instrument.exchange}")

        for tf, df in candle_data.items():
            candles_list = df.to_dict("records")
            saved = await save_candles(
                session=session,
                instrument_id=instrument.id,
                timeframe=tf,
                candles=candles_list,
            )
            print(f"  Saved {saved} new {tf} candles (total in df: {len(df)})")

    # Step 5: Verify via DB reload
    print(f"\n{'-' * 50}")
    print("Verifying data from database...")

    from app.pipeline.db_persistence import load_candles

    async with async_session() as session:
        for tf in candle_data:
            df_db = await load_candles(session, instrument.id, tf)
            print(f"  {tf}: {len(df_db)} candles in DB")
            if not df_db.empty:
                print(f"    Range: {df_db['timestamp'].iloc[0]} -> {df_db['timestamp'].iloc[-1]}")
                print(f"    Latest: O={df_db['open'].iloc[-1]:.2f} H={df_db['high'].iloc[-1]:.2f} "
                      f"L={df_db['low'].iloc[-1]:.2f} C={df_db['close'].iloc[-1]:.2f}")

    # Step 6: Try API verification (if backend is running)
    print(f"\n{'-' * 50}")
    print("Verifying via REST API...")

    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            health = await client.get("http://localhost:8000/api/health")
            if health.status_code == 200:
                print("  Backend is running!")

                # Candles
                resp = await client.get(
                    "http://localhost:8000/api/charts/candles",
                    params={"symbol": name, "exchange": exchange, "interval": "1d", "days": 365},
                )
                if resp.status_code == 200:
                    api_data = resp.json()
                    print(f"  Candles API: {api_data.get('count', 0)} candles (source={api_data.get('source')})")

                # Indicators
                resp = await client.get(
                    "http://localhost:8000/api/indicators/compute",
                    params={"symbol": name, "exchange": exchange, "interval": "1d", "days": 365},
                )
                if resp.status_code == 200:
                    ind_data = resp.json()
                    print(f"  Indicators API: {ind_data.get('count', 0)} data points")
                    ema13 = [v for v in (ind_data.get("data", {}).get("ema13") or []) if v is not None]
                    if ema13:
                        print(f"    EMA-13 latest: {ema13[-1]:.2f}")

                # Screen config
                resp = await client.get(
                    "http://localhost:8000/api/strategy/screen-config",
                    params={"symbol": name, "exchange": exchange},
                )
                if resp.status_code == 200:
                    cfg = resp.json()
                    print(f"  Screen config: asset_class={cfg.get('asset_class')}")
                    for s, info in cfg.get("screens", {}).items():
                        print(f"    Screen {s}: {info.get('timeframe')}")
            else:
                print("  Backend not healthy")
    except Exception as e:
        print(f"  Backend not running ({e}), skipping API check")

    print(f"\n{'=' * 60}")
    print("GOLDM data pipeline complete!")
    print(f"  Contract: {symbol}")
    print(f"  Token:    {token}")
    print(f"  Exchange: {exchange}")
    for tf, df in candle_data.items():
        print(f"  {tf}: {len(df)} candles")


def main():
    asyncio.run(fill_goldm_data())


if __name__ == "__main__":
    main()
