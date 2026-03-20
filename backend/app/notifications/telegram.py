"""Telegram notification service for Elder Trading System.

Sends formatted alerts for:
- Signal generation (Triple Screen analysis)
- Trade execution (paper/live)
- Circuit breaker halt
- System status changes
"""

import httpx
from loguru import logger

from app.config import settings

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _is_configured() -> bool:
    """Check if Telegram is properly configured."""
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


async def _send(text: str, parse_mode: str = "HTML") -> bool:
    """Send a message via Telegram Bot API."""
    if not _is_configured():
        return False

    url = TELEGRAM_API.format(token=settings.telegram_bot_token)
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                return True
            logger.warning("Telegram send failed: {} {}", resp.status_code, resp.text[:100])
            return False
    except Exception as e:
        logger.warning("Telegram send error: {}", e)
        return False


# ── Signal Alert ──────────────────────────────────────────────

async def notify_signal(symbol: str, analysis: dict):
    """Send Triple Screen signal alert."""
    rec = analysis.get("recommendation", {})
    action = rec.get("action", "WAIT")
    if action == "WAIT":
        return  # Don't spam WAIT signals

    grade = analysis.get("grade", "?")
    confidence = rec.get("confidence", 0)
    entry = rec.get("entry_price", 0)
    stop = rec.get("stop_price", 0)
    entry_type = rec.get("entry_type", "MARKET")

    # Screen details
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

    await _send(text)


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

    text = (
        f"{emoji} <b>TRADE EXECUTED</b> ({mode})\n"
        f"\n"
        f"{dir_emoji} <b>{direction} {symbol}</b>\n"
        f"Qty: <b>{quantity}</b>  |  Price: ₹{price:,.2f}\n"
        f"Stop: ₹{stop_price:,.2f}\n"
        f"Risk: ₹{risk:,.2f}\n"
        f"Order: {order_id}  |  Grade: {grade}\n"
    )

    await _send(text)


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

    await _send(text)


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

    await _send(text)


async def notify_feed_status(connected: bool, symbol: str = ""):
    """Send feed connection status change."""
    if connected:
        text = f"📡 <b>Feed Connected</b> — {symbol} live ticks flowing"
    else:
        text = f"⚠️ <b>Feed Disconnected</b> — switching to demo/offline mode"

    await _send(text)
