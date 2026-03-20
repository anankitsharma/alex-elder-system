"""Setup Telegram bot — get chat ID and send test message.

Usage:
  1. Message your bot on Telegram first (send /start)
  2. Run: python scripts/setup_telegram.py
  3. It will find your chat ID and send a test message
  4. Add the chat ID to .env: TELEGRAM_CHAT_ID=<your_id>
"""

import os
import sys
import httpx

# Load .env
from pathlib import Path
env_path = Path(__file__).resolve().parents[1] / ".env"
with open(env_path, encoding="utf-8", errors="ignore") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
if not TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN not set in .env")
    sys.exit(1)

BASE = f"https://api.telegram.org/bot{TOKEN}"

# Step 1: Get updates to find chat ID
print(f"Bot token: {TOKEN[:10]}...{TOKEN[-5:]}")
print("\nFetching updates...")
resp = httpx.get(f"{BASE}/getUpdates", timeout=10)
data = resp.json()

if not data.get("ok"):
    print(f"API error: {data}")
    sys.exit(1)

results = data.get("result", [])
if not results:
    print("\nNo messages found. Please:")
    print("  1. Open Telegram")
    print("  2. Search for your bot")
    print("  3. Send /start to the bot")
    print("  4. Run this script again")
    sys.exit(0)

# Find unique chat IDs
chats = {}
for update in results:
    msg = update.get("message", {})
    chat = msg.get("chat", {})
    if chat.get("id"):
        chats[chat["id"]] = {
            "type": chat.get("type"),
            "name": chat.get("first_name", "") + " " + chat.get("last_name", ""),
            "username": chat.get("username", ""),
        }

print(f"\nFound {len(chats)} chat(s):")
for chat_id, info in chats.items():
    print(f"  Chat ID: {chat_id}")
    print(f"  Name: {info['name'].strip()}")
    print(f"  Username: @{info['username']}")
    print(f"  Type: {info['type']}")
    print()

# Use first chat ID
chat_id = list(chats.keys())[0]
print(f"Using chat ID: {chat_id}")

# Step 2: Send test message
print("\nSending test message...")
test_msg = (
    "🚀 <b>Elder Trading System</b>\n\n"
    "✅ Telegram notifications configured!\n\n"
    "You will receive:\n"
    "• 🟢🔴 Signal alerts (BUY/SELL)\n"
    "• ✅ Trade execution confirmations\n"
    "• 🛑 Circuit breaker warnings\n"
    "• 📡 System status updates\n"
)
resp = httpx.post(
    f"{BASE}/sendMessage",
    json={"chat_id": chat_id, "text": test_msg, "parse_mode": "HTML"},
    timeout=10,
)
result = resp.json()
if result.get("ok"):
    print("✅ Test message sent successfully!")
    print(f"\nAdd this to your .env file:")
    print(f"  TELEGRAM_CHAT_ID={chat_id}")
else:
    print(f"❌ Failed: {result}")
