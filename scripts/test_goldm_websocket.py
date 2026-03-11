"""Script: Test live WebSocket feed for GOLDM on MCX.

Connects to Angel One WebSocket feed, subscribes to GOLDM,
and prints live ticks for 60 seconds. Use this during MCX hours
(10:00 AM - 11:30 PM IST) to verify real-time data flow.

Usage:
    cd backend && python ../scripts/test_goldm_websocket.py

Requires .env with Angel One feed credentials.
"""

import sys
import time
import threading
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

tick_count = 0
last_price = None


def on_tick(tick_data):
    """Callback for each tick received."""
    global tick_count, last_price
    tick_count += 1

    if isinstance(tick_data, dict):
        token = tick_data.get("token", "?")
        ltp = tick_data.get("last_traded_price", tick_data.get("ltp", 0))
        # Angel One sends prices * 100 for some instruments
        if isinstance(ltp, (int, float)) and ltp > 1_000_000:
            ltp = ltp / 100
        vol = tick_data.get("volume_trade_today", tick_data.get("volume", 0))
        last_price = ltp
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [{ts}] Tick #{tick_count}: token={token} LTP={ltp} Vol={vol}")
    else:
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [{ts}] Tick #{tick_count}: {type(tick_data).__name__} len={len(tick_data) if hasattr(tick_data, '__len__') else '?'}")


def main():
    print("=" * 60)
    print("GOLDM Live WebSocket Feed Test")
    print("=" * 60)
    print(f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}")
    print("MCX hours: 10:00 AM - 11:30 PM IST")
    print()

    # Step 1: Find GOLDM token
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
    exchange = "MCX"
    print(f"Contract: {symbol} (token={token}, exchange={exchange})")

    # Step 2: Login to Angel One feed
    print("\nLogging in to Angel One (all sessions)...")
    from app.broker.angel_client import angel

    try:
        success = angel.login_all()
        if not success:
            print("Some logins failed, trying feed-only...")
            result = angel.login_feed()
            if not result.get("status"):
                print(f"Feed login failed: {result}")
                return
        print("Login OK!")
    except Exception as e:
        print(f"Login error: {e}")
        return

    # Step 3: Pre-subscribe GOLDM BEFORE connecting
    print(f"\nPre-subscribing GOLDM token={token} on MCX...")
    from app.broker.websocket_feed import market_feed

    market_feed.add_callback(on_tick)
    market_feed.subscribe([token], exchange)
    print(f"  Subscription registered (will activate on connect)")

    # Step 4: Connect WebSocket in background thread (connect() is blocking)
    print("\nConnecting to Angel One WebSocket feed...")

    def run_feed():
        try:
            market_feed.connect()
        except Exception as e:
            print(f"WebSocket connect error: {e}")

    feed_thread = threading.Thread(target=run_feed, daemon=True)
    feed_thread.start()

    # Wait for connection
    print("Waiting for WebSocket connection...")
    for i in range(15):
        if market_feed.is_connected:
            break
        time.sleep(1)
        print(f"  ...waiting ({i+1}s)")

    if not market_feed.is_connected:
        print("ERROR: WebSocket failed to connect after 15s")
        return

    print(f"Connected! is_connected={market_feed.is_connected}")

    # Give subscription time to activate
    time.sleep(2)

    # Step 5: Wait and collect ticks
    duration = 60
    print(f"\nListening for ticks for {duration} seconds...")
    print("-" * 60)

    start = time.time()
    while (time.time() - start) < duration:
        time.sleep(1)
        elapsed = int(time.time() - start)
        if elapsed % 15 == 0 and elapsed > 0:
            rate = tick_count / elapsed if elapsed > 0 else 0
            print(f"  --- {elapsed}s elapsed: {tick_count} ticks total ({rate:.1f}/s) ---")

    print("-" * 60)
    print(f"\nResults:")
    print(f"  Total ticks received: {tick_count}")
    print(f"  Last price: {last_price}")
    print(f"  Duration: {duration}s")
    print(f"  Rate: {tick_count / duration:.1f} ticks/sec")

    if tick_count == 0:
        print("\n  WARNING: No ticks received!")
        print("  Possible reasons:")
        print("    - MCX market is closed (check hours: 10AM-11:30PM IST)")
        print("    - Feed credentials invalid or session expired")
        print("    - Token not recognized by Angel One for this contract")
        print("    - Network/firewall blocking WebSocket")
        print(f"\n  Debug info:")
        print(f"    feed._subscriptions: {market_feed._subscriptions}")
        print(f"    feed._running: {market_feed._running}")
        print(f"    feed._last_data_time: {market_feed._last_data_time}")

    # Cleanup
    print("\nDisconnecting...")
    market_feed.disconnect()
    print("Done!")


if __name__ == "__main__":
    main()
