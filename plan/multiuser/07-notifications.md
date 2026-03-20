# Phase 7: Per-User Notifications

## Current State

- Single Telegram bot token + single chat_id in `.env`
- Single Discord webhook URL in `.env`
- All alerts go to same channels
- `notify_*` functions have no user concept

## Architecture

```
Single Telegram Bot (shared)
├── User A chat_id: "123456" → DM to User A
├── User B chat_id: "789012" → DM to User B
└── User C chat_id: ""        → No Telegram (disabled)
```

One bot, multiple users. Each user has their own Telegram `chat_id` stored in `user_notifications` table.

## User Onboarding (Telegram)

1. Admin shares bot link: `https://t.me/ElderTradingBot`
2. User clicks link, sends `/start` to bot
3. Bot receives user's `chat_id`
4. User enters their linking code (generated in web UI)
5. Bot associates `chat_id` with `user_id` in DB

Alternative (simpler for 2-10 users): Admin manually enters each user's `chat_id` via the web UI settings page.

## Changes to `notifications/telegram.py`

### Add user resolution

```python
async def _get_user_notification_config(user_id: int) -> dict:
    """Load user's notification preferences from DB."""
    async with async_session() as session:
        stmt = select(UserNotificationConfig).where(
            UserNotificationConfig.user_id == user_id
        )
        result = await session.execute(stmt)
        config = result.scalar_one_or_none()

    if not config:
        return {"telegram_chat_id": "", "discord_webhook_url": "", "min_priority": 1}

    return {
        "telegram_chat_id": config.telegram_chat_id,
        "discord_webhook_url": config.discord_webhook_url,
        "min_priority": config.min_priority,
        "alerts_enabled": config.alerts_enabled,
    }
```

### Update `_send()` signature

```python
# Before:
async def _send(text: str, priority=Priority.NORMAL, discord_color=None):

# After:
async def _send(text: str, priority=Priority.NORMAL, discord_color=None, user_id: int = None):
    """Send notification to a specific user's channels.

    If user_id is None, falls back to system-level channels (from .env).
    """
    if user_id:
        config = await _get_user_notification_config(user_id)
        if not config["alerts_enabled"]:
            return False
        if priority.value < config["min_priority"]:
            return False
        chat_id = config["telegram_chat_id"]
        webhook = config["discord_webhook_url"]
    else:
        # System-level (startup, shutdown, errors)
        chat_id = settings.telegram_chat_id
        webhook = settings.discord_webhook_url
```

### Update all `notify_*` functions

Add `user_id` parameter to every notification function:

```python
async def notify_signal(symbol, direction, confidence, grade, user_id: int = None):
async def notify_trade(symbol, direction, qty, price, stop, order_id, mode, grade, user_id: int = None):
async def notify_position_closed(symbol, direction, entry, exit, qty, pnl, reason, ..., user_id: int = None):
async def notify_trailing_stop(symbol, direction, old_stop, new_stop, user_id: int = None):
async def notify_circuit_breaker(reason, pct, user_id: int = None):
async def notify_order_rejected(symbol, direction, qty, reason, mode, user_id: int = None):
```

System-level notifications (no user_id) stay unchanged:
```python
async def notify_system_start():      # System
async def notify_system_shutdown():   # System
async def notify_feed_status(...):    # System
async def notify_daily_summary(...):  # Sent to ALL users
```

### Per-user rate limiting

Change rate limit tracking from global to per-user:

```python
# Before:
_rate_timestamps: dict[str, deque] = {"telegram": deque(), "discord": deque()}

# After:
_rate_timestamps: dict[str, deque] = {}  # "telegram:user_1" -> deque()

def _check_rate(channel: str, user_id: int = None) -> bool:
    key = f"{channel}:{user_id}" if user_id else channel
    ...
```

## Daily Summary

Send to ALL users:
```python
async def send_daily_summary():
    """Send daily P&L summary to each user with their own trades."""
    async with async_session() as session:
        users = await session.execute(select(User).where(User.is_active == True))
        for user in users.scalars().all():
            user_trades = await db.load_month_trades(session, month_str, user_id=user.id)
            # Format user-specific summary
            await _send(summary_text, priority=Priority.NORMAL, user_id=user.id)
```

## Caller Changes

Every place that calls `notify_*` must pass `user_id`:

- `asset_session.py` → `notify_trade(... user_id=self.user_id)`
- `market_stream.py` → `notify_position_closed(... user_id=session.user_id)`
- `market_stream.py` → `notify_order_rejected(... user_id=session.user_id)`
