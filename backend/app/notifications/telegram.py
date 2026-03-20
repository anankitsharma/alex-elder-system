"""Multi-channel notification service for Elder Trading System.

Channels:
  - Telegram Bot API (primary)
  - Discord Webhook (secondary)

Features:
  - Retry with exponential backoff (3 attempts)
  - Rate limiting (max 20 messages/minute per channel)
  - Priority levels: CRITICAL (always send), HIGH, NORMAL, LOW
  - Message dedup (no repeat within 60s for same content hash)
  - Graceful degradation (logs warning if all channels fail)

Event types:
  - Signal generation (Triple Screen)
  - Trade execution (paper/live)
  - Position closed (stop loss / target / EOD / flip)
  - Trailing stop update
  - Circuit breaker halt/reset
  - System status (startup, feed connect/disconnect)
  - Daily P&L summary
  - Error alerts (broker failure, order rejection)
  - Contract rollover
"""

import asyncio
import hashlib
import time
from collections import deque
from enum import IntEnum
from typing import Optional

import httpx
from loguru import logger

from app.config import settings

# ── Constants ─────────────────────────────────────────────────

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 20  # max messages per window
DEDUP_WINDOW = 60  # seconds — suppress duplicate messages


class Priority(IntEnum):
    LOW = 0       # Informational (trailing stop, alignment level 1)
    NORMAL = 1    # Standard events (trade execution, signals)
    HIGH = 2      # Important (stop/target hit, circuit breaker)
    CRITICAL = 3  # Must-deliver (system errors, live trade failures)


# ── Rate limiter + dedup state ────────────────────────────────

_telegram_timestamps: deque = deque()
_discord_timestamps: deque = deque()
_recent_hashes: dict[str, float] = {}  # hash -> timestamp

# ── Notification retry queue ─────────────────────────────────
# When rate limited, messages are queued here instead of dropped.
# CRITICAL priority messages bypass the rate limit entirely.
_notification_queue: list = []  # list of (text, priority, kwargs) tuples
_flush_lock = False  # simple re-entrancy guard


def _is_rate_limited(timestamps: deque) -> bool:
    """Check if we've exceeded rate limit for a channel."""
    now = time.time()
    # Purge old timestamps
    while timestamps and timestamps[0] < now - RATE_LIMIT_WINDOW:
        timestamps.popleft()
    return len(timestamps) >= RATE_LIMIT_MAX


def _record_send(timestamps: deque):
    """Record a send timestamp."""
    timestamps.append(time.time())


def _is_duplicate(text: str) -> bool:
    """Check if this exact message was sent recently."""
    now = time.time()
    # Clean old entries
    expired = [k for k, v in _recent_hashes.items() if now - v > DEDUP_WINDOW]
    for k in expired:
        del _recent_hashes[k]

    msg_hash = hashlib.md5(text.encode()).hexdigest()[:12]
    if msg_hash in _recent_hashes:
        return True
    _recent_hashes[msg_hash] = now
    return False


# ── Channel: Telegram ─────────────────────────────────────────

def _is_telegram_configured() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


async def _send_telegram(
    text: str, parse_mode: str = "HTML",
    _bypass_rate_limit: bool = False, _chat_id_override: str = "",
) -> bool:
    """Send via Telegram with retry + backoff."""
    chat_id = _chat_id_override or settings.telegram_chat_id
    if not settings.telegram_bot_token or not chat_id:
        return False

    if not _bypass_rate_limit and _is_rate_limited(_telegram_timestamps):
        logger.warning("Telegram rate limited — message queued for retry")
        return False

    url = TELEGRAM_API.format(token=settings.telegram_bot_token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    _record_send(_telegram_timestamps)
                    return True
                elif resp.status_code == 429:
                    # Telegram rate limit hit — wait and retry
                    retry_after = int(resp.headers.get("Retry-After", 5))
                    logger.warning("Telegram 429 — waiting {}s", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                else:
                    logger.warning("Telegram {} on attempt {}: {}",
                                   resp.status_code, attempt + 1, resp.text[:100])
        except Exception as e:
            logger.warning("Telegram error attempt {}: {}", attempt + 1, e)

        if attempt < MAX_RETRIES - 1:
            await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))

    return False


# ── Channel: Discord Webhook ──────────────────────────────────

def _is_discord_configured() -> bool:
    return bool(getattr(settings, "discord_webhook_url", ""))


async def _send_discord(
    text: str, color: int = 0x2ECC71,
    _bypass_rate_limit: bool = False, _webhook_override: str = "",
) -> bool:
    """Send via Discord webhook as an embed."""
    webhook_url = _webhook_override or getattr(settings, "discord_webhook_url", "")
    if not webhook_url:
        return False

    if not _bypass_rate_limit and _is_rate_limited(_discord_timestamps):
        logger.warning("Discord rate limited — message queued for retry")
        return False

    # Convert HTML to plain text for Discord
    import re
    plain = re.sub(r"<[^>]+>", "", text)

    # Split into title (first line) and body
    lines = plain.strip().split("\n", 1)
    title = lines[0].strip()
    description = lines[1].strip() if len(lines) > 1 else ""

    payload = {
        "embeds": [{
            "title": title,
            "description": description,
            "color": color,
            "footer": {"text": f"Elder Trading • {settings.trading_mode}"},
        }],
    }

    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(webhook_url, json=payload)
                if resp.status_code in (200, 204):
                    _record_send(_discord_timestamps)
                    return True
                elif resp.status_code == 429:
                    retry_after = float(resp.json().get("retry_after", 5))
                    await asyncio.sleep(retry_after)
                    continue
        except Exception as e:
            logger.warning("Discord error attempt {}: {}", attempt + 1, e)

        if attempt < MAX_RETRIES - 1:
            await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))

    return False


# ── Unified Send ──────────────────────────────────────────────

# Discord embed colors by event type
DISCORD_COLORS = {
    "buy": 0x2ECC71,     # Green
    "sell": 0xE74C3C,    # Red
    "stop": 0xE67E22,    # Orange
    "target": 0x3498DB,  # Blue
    "info": 0x95A5A6,    # Gray
    "error": 0xE74C3C,   # Red
    "success": 0x2ECC71, # Green
}


async def _flush_notification_queue() -> None:
    """Retry queued messages that were rate-limited.

    Called after a successful send to drain the queue while capacity exists.
    Uses a simple boolean guard to prevent re-entrant flushes.
    """
    global _flush_lock
    if _flush_lock or not _notification_queue:
        return

    _flush_lock = True
    try:
        while _notification_queue:
            # Stop if both channels are rate-limited — no point retrying yet
            tg_limited = _is_telegram_configured() and _is_rate_limited(_telegram_timestamps)
            dc_limited = _is_discord_configured() and _is_rate_limited(_discord_timestamps)
            if tg_limited and dc_limited:
                break
            if not _is_telegram_configured() and dc_limited:
                break
            if not _is_discord_configured() and tg_limited:
                break

            queued_text, queued_priority, queued_kwargs = _notification_queue.pop(0)
            results = []

            if _is_telegram_configured():
                results.append(await _send_telegram(
                    queued_text,
                    queued_kwargs.get("parse_mode", "HTML"),
                ))

            if _is_discord_configured():
                color = DISCORD_COLORS.get(
                    queued_kwargs.get("discord_color", "info"), 0x95A5A6
                )
                results.append(await _send_discord(queued_text, color))

            sent = any(results)
            if sent:
                logger.debug("Flushed queued notification: {}...", queued_text[:60])
            else:
                # Still rate-limited — put it back at the front
                _notification_queue.insert(0, (queued_text, queued_priority, queued_kwargs))
                break
    finally:
        _flush_lock = False


async def _send(
    text: str,
    parse_mode: str = "HTML",
    priority: Priority = Priority.NORMAL,
    discord_color: str = "info",
    user_id: int = None,
) -> bool:
    """Send notification to configured channels.

    If user_id is provided, sends to that user's personal channels (from DB).
    Otherwise sends to system-level channels (from .env).

    Args:
        text: HTML-formatted message text
        parse_mode: Telegram parse mode (HTML default)
        priority: Message priority level
        discord_color: Color key for Discord embed
        user_id: Target user (None = system-level channels)

    Returns:
        True if at least one channel succeeded
    """
    # Skip duplicates (except CRITICAL)
    if priority < Priority.CRITICAL and _is_duplicate(text):
        return False

    # CRITICAL messages bypass rate limits entirely
    bypass = priority >= Priority.CRITICAL

    # Resolve per-user channels if user_id provided
    user_chat_id = None
    user_webhook = None
    if user_id:
        try:
            from app.database import async_session as _get_session
            from sqlalchemy import select
            from app.models.user import UserNotificationConfig
            async with _get_session() as session:
                result = await session.execute(
                    select(UserNotificationConfig).where(
                        UserNotificationConfig.user_id == user_id
                    )
                )
                config = result.scalar_one_or_none()
                if config:
                    if not config.alerts_enabled:
                        return False
                    if priority.value < config.min_priority:
                        return False
                    user_chat_id = config.telegram_chat_id
                    user_webhook = config.discord_webhook_url
        except Exception:
            pass  # Fall back to system channels

    results = []

    # Telegram
    if user_chat_id:
        results.append(await _send_telegram(
            text, parse_mode, _bypass_rate_limit=bypass, _chat_id_override=user_chat_id,
        ))
    elif _is_telegram_configured() and not user_id:
        results.append(await _send_telegram(text, parse_mode, _bypass_rate_limit=bypass))

    # Discord
    if user_webhook:
        color = DISCORD_COLORS.get(discord_color, 0x95A5A6)
        results.append(await _send_discord(
            text, color, _bypass_rate_limit=bypass, _webhook_override=user_webhook,
        ))
    elif _is_discord_configured() and not user_id:
        color = DISCORD_COLORS.get(discord_color, 0x95A5A6)
        results.append(await _send_discord(text, color, _bypass_rate_limit=bypass))

    if not results:
        # No channels configured
        return False

    success = any(results)

    if not success and not bypass:
        # All channels rate-limited — queue for retry instead of dropping
        _notification_queue.append((text, priority, {
            "parse_mode": parse_mode,
            "discord_color": discord_color,
        }))
        logger.info("Notification queued ({} pending): {}...",
                     len(_notification_queue), text[:60])
        return False

    if not success and priority >= Priority.HIGH:
        logger.error("NOTIFICATION FAILED (priority={}): {}", priority.name, text[:100])

    # After a successful send, try to flush queued messages
    if success and _notification_queue:
        await _flush_notification_queue()

    return success


# ── Backward-compatible alias ─────────────────────────────────
_is_configured = _is_telegram_configured


# ══════════════════════════════════════════════════════════════
# EVENT-SPECIFIC NOTIFICATION FUNCTIONS
# ══════════════════════════════════════════════════════════════

# ── Signal Alert ──────────────────────────────────────────────

async def notify_signal(symbol: str, analysis: dict):
    """Send Triple Screen signal alert."""
    rec = analysis.get("recommendation", {})
    action = rec.get("action", "WAIT")
    if action == "WAIT":
        return

    grade = analysis.get("grade", "?")
    confidence = rec.get("confidence", 0)
    entry = rec.get("entry_price", 0)
    stop = rec.get("stop_price", 0)
    entry_type = rec.get("entry_type", "MARKET")

    s1 = analysis.get("screen1", {})
    s2 = analysis.get("screen2", {})
    tide = s1.get("tide", "?")
    wave_signal = s2.get("signal", "?")

    risk = abs(entry - stop) if entry and stop else 0
    risk_pct = (risk / entry * 100) if entry else 0

    emoji = "🟢" if action == "BUY" else "🔴"
    grade_emoji = {"A": "⭐⭐⭐", "B": "⭐⭐", "C": "⭐", "D": "⚠️"}.get(grade, "")

    text = (
        f"{emoji} <b>SIGNAL: {action} {symbol}</b>\n"
        f"\n"
        f"Grade: <b>{grade}</b> {grade_emoji}  |  Confidence: <b>{confidence}%</b>\n"
        f"Entry: <b>{entry_type}</b> @ ₹{entry:,.2f}\n"
        f"Stop: ₹{stop:,.2f}  |  Risk: ₹{risk:,.2f} ({risk_pct:.1f}%)\n"
        f"\n"
        f"Screen 1 (Tide): <b>{tide}</b>\n"
        f"Screen 2 (Wave): <b>{wave_signal}</b>\n"
        f"\n"
        f"Mode: <b>{settings.trading_mode}</b>"
    )

    color = "buy" if action == "BUY" else "sell"
    await _send(text, priority=Priority.NORMAL, discord_color=color)


# ── Trade Execution Alert ─────────────────────────────────────

async def notify_trade(
    symbol: str,
    direction: str,
    quantity: int,
    price: float,
    stop_price: float,
    order_id: str,
    mode: str = "PAPER",
    grade: str = "?",
):
    """Send trade execution notification."""
    emoji = "✅" if mode == "PAPER" else "🔥"
    dir_emoji = "📈" if direction == "BUY" else "📉"
    risk = abs(price - stop_price) * quantity

    # Calculate target (2:1 R:R)
    risk_per = abs(price - stop_price)
    if direction == "BUY":
        target = price + risk_per * 2
    else:
        target = price - risk_per * 2

    text = (
        f"{emoji} <b>TRADE EXECUTED</b> ({mode})\n"
        f"\n"
        f"{dir_emoji} <b>{direction} {symbol}</b>\n"
        f"Qty: <b>{quantity}</b>  |  Entry: ₹{price:,.2f}\n"
        f"Stop: ₹{stop_price:,.2f}  |  Target: ₹{target:,.2f}\n"
        f"Risk: ₹{risk:,.2f}  |  R:R = 1:2\n"
        f"Order: <code>{order_id}</code>  |  Grade: {grade}\n"
    )

    priority = Priority.HIGH if mode == "LIVE" else Priority.NORMAL
    color = "buy" if direction == "BUY" else "sell"
    await _send(text, priority=priority, discord_color=color)


# ── Position Closed Alert ─────────────────────────────────────

async def notify_position_closed(
    symbol: str,
    direction: str,
    entry_price: float,
    exit_price: float,
    quantity: int,
    pnl: float,
    reason: str,
    stop_price: float = 0,
    target_price: float = 0,
    mode: str = "PAPER",
):
    """Send position closed notification (stop/target/EOD/flip)."""
    # Emoji by exit reason
    reason_display = {
        "STOP_LOSS": ("🛑", "STOP LOSS HIT"),
        "TARGET": ("🎯", "TARGET HIT"),
        "EOD": ("🔔", "EOD AUTO-CLOSE"),
        "FLIP": ("🔄", "POSITION FLIPPED"),
        "MANUAL": ("✋", "MANUAL CLOSE"),
        "SIGNAL": ("📊", "SIGNAL EXIT"),
    }
    emoji, title = reason_display.get(reason, ("📤", reason))

    # P&L emoji
    pnl_emoji = "💰" if pnl > 0 else "💸" if pnl < 0 else "➖"
    pnl_sign = "+" if pnl > 0 else ""

    # R-multiple (how many R did we make/lose)
    risk_per = abs(entry_price - stop_price) if stop_price else 0
    r_multiple = pnl / (risk_per * quantity) if risk_per > 0 and quantity > 0 else 0

    text = (
        f"{emoji} <b>{title}: {symbol}</b> ({mode})\n"
        f"\n"
        f"Direction: {direction}\n"
        f"Entry: ₹{entry_price:,.2f} → Exit: ₹{exit_price:,.2f}\n"
    )
    if stop_price:
        text += f"Stop: ₹{stop_price:,.2f}"
        if target_price:
            text += f"  |  Target: ₹{target_price:,.2f}"
        text += "\n"

    text += (
        f"Qty: {quantity}\n"
        f"\n"
        f"{pnl_emoji} P&L: <b>{pnl_sign}₹{pnl:,.2f}</b>"
    )
    if r_multiple:
        text += f"  ({pnl_sign}{r_multiple:.1f}R)"
    text += "\n"

    priority = Priority.HIGH if mode == "LIVE" else Priority.NORMAL
    color = "success" if pnl > 0 else "stop" if pnl < 0 else "info"
    await _send(text, priority=priority, discord_color=color)


# ── Trailing Stop Update ──────────────────────────────────────

async def notify_trailing_stop(
    symbol: str,
    direction: str,
    old_stop: float,
    new_stop: float,
    ltp: float,
):
    """Send trailing stop update notification (LOW priority — won't spam)."""
    text = (
        f"📐 <b>TRAILING STOP: {symbol}</b>\n"
        f"\n"
        f"Direction: {direction}\n"
        f"Stop: ₹{old_stop:,.2f} → ₹{new_stop:,.2f}\n"
        f"LTP: ₹{ltp:,.2f}"
    )

    await _send(text, priority=Priority.LOW, discord_color="info")


# ── Circuit Breaker Alert ─────────────────────────────────────

async def notify_circuit_breaker(reason: str, exposure_pct: float):
    """Send circuit breaker halt notification."""
    text = (
        f"🛑 <b>CIRCUIT BREAKER HALT</b>\n"
        f"\n"
        f"Reason: {reason}\n"
        f"Portfolio exposure: <b>{exposure_pct:.1f}%</b> (limit: {settings.max_portfolio_risk_pct}%)\n"
        f"\n"
        f"⚠️ New trades blocked until next month or manual reset."
    )

    await _send(text, priority=Priority.CRITICAL, discord_color="error")


async def notify_circuit_breaker_reset():
    """Send circuit breaker reset notification (monthly)."""
    text = (
        f"✅ <b>CIRCUIT BREAKER RESET</b>\n"
        f"\n"
        f"New month — trading resumed.\n"
        f"Portfolio risk limit: {settings.max_portfolio_risk_pct}%"
    )

    await _send(text, priority=Priority.NORMAL, discord_color="success")


# ── Error Alerts ──────────────────────────────────────────────

async def notify_error(title: str, details: str, symbol: str = ""):
    """Send error/failure notification."""
    sym_part = f" ({symbol})" if symbol else ""
    text = (
        f"⚠️ <b>ERROR{sym_part}</b>\n"
        f"\n"
        f"<b>{title}</b>\n"
        f"{details}"
    )

    await _send(text, priority=Priority.HIGH, discord_color="error")


async def notify_order_rejected(
    symbol: str,
    direction: str,
    quantity: int,
    reason: str,
    mode: str = "PAPER",
):
    """Send order rejection notification."""
    text = (
        f"❌ <b>ORDER REJECTED: {symbol}</b> ({mode})\n"
        f"\n"
        f"Direction: {direction}  |  Qty: {quantity}\n"
        f"Reason: {reason}"
    )

    priority = Priority.CRITICAL if mode == "LIVE" else Priority.HIGH
    await _send(text, priority=priority, discord_color="error")


# ── System Status ─────────────────────────────────────────────

async def notify_system_start():
    """Send system startup notification."""
    text = (
        f"🚀 <b>Elder Trading System Started</b>\n"
        f"\n"
        f"Mode: <b>{settings.trading_mode}</b>\n"
        f"Risk: {settings.max_risk_per_trade_pct}% per trade, "
        f"{settings.max_portfolio_risk_pct}% portfolio\n"
        f"Min signal score: {settings.min_signal_score}\n"
    )

    await _send(text, priority=Priority.HIGH, discord_color="success")


async def notify_feed_status(connected: bool, symbol: str = ""):
    """Send feed connection status change."""
    if connected:
        text = f"📡 <b>Feed Connected</b> — {symbol} live ticks flowing"
        priority = Priority.NORMAL
        color = "success"
    else:
        text = f"⚠️ <b>Feed Disconnected</b> — switching to demo/offline mode"
        priority = Priority.HIGH
        color = "error"

    await _send(text, priority=priority, discord_color=color)


async def notify_system_shutdown():
    """Send system shutdown notification."""
    text = "🔴 <b>Elder Trading System Stopped</b>"
    await _send(text, priority=Priority.HIGH, discord_color="error")


# ── Daily P&L Summary ────────────────────────────────────────

async def notify_daily_summary(
    date_str: str,
    total_trades: int,
    winners: int,
    losers: int,
    total_pnl: float,
    win_rate: float,
    best_trade: Optional[dict] = None,
    worst_trade: Optional[dict] = None,
    open_positions: int = 0,
):
    """Send end-of-day P&L summary."""
    pnl_emoji = "📈" if total_pnl > 0 else "📉" if total_pnl < 0 else "➖"
    pnl_sign = "+" if total_pnl > 0 else ""

    text = (
        f"📊 <b>DAILY SUMMARY — {date_str}</b>\n"
        f"\n"
        f"Trades: <b>{total_trades}</b>  |  W: {winners}  L: {losers}\n"
        f"Win Rate: <b>{win_rate:.0f}%</b>\n"
        f"\n"
        f"{pnl_emoji} Day P&L: <b>{pnl_sign}₹{total_pnl:,.2f}</b>\n"
    )

    if best_trade:
        text += f"\n🏆 Best: {best_trade['symbol']} +₹{best_trade['pnl']:,.2f}"
    if worst_trade:
        text += f"\n💀 Worst: {worst_trade['symbol']} -₹{abs(worst_trade['pnl']):,.2f}"

    if open_positions > 0:
        text += f"\n\n📌 Open positions: {open_positions}"

    text += f"\n\nMode: {settings.trading_mode}"

    await _send(text, priority=Priority.NORMAL, discord_color="success" if total_pnl >= 0 else "stop")


# ── Contract Rollover ─────────────────────────────────────────

async def notify_rollover(
    symbol: str,
    old_contract: str,
    new_contract: str,
    new_token: str,
    expiry: str,
    days_left: int,
):
    """Send contract rollover notification."""
    text = (
        f"🔄 <b>CONTRACT ROLLOVER: {symbol}</b>\n"
        f"\n"
        f"Old: {old_contract}\n"
        f"New: <b>{new_contract}</b> (token {new_token})\n"
        f"Expiry: {expiry}\n"
        f"Days left: {days_left}"
    )

    await _send(text, priority=Priority.NORMAL, discord_color="info")
