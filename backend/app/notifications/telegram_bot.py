"""Telegram bot command handler — allows querying system status from Telegram.

Commands:
  /status  — Overview of all assets, positions, equity
  /pos     — Open positions with P&L
  /funds   — Available balance, utilized, net equity
  /nifty   — NIFTY detail (tide, wave, signal, entry/stop)
  /banknifty — BANKNIFTY detail
  /goldm   — GOLDM detail
  /silverm, /copper, /aluminium, /zinc, /natgasmini, /crudeoilm
  /signals — Recent signals
  /kill    — Activate kill switch
  /help    — List commands
"""

import asyncio
import httpx
from loguru import logger
from app.config import settings

API_BASE = "https://api.telegram.org/bot{token}"
POLL_INTERVAL = 2  # seconds

# Map short names to full symbols
SYMBOL_MAP = {
    "nifty": ("NIFTY", "NFO"),
    "banknifty": ("BANKNIFTY", "NFO"),
    "goldm": ("GOLDM", "MCX"),
    "gold": ("GOLDM", "MCX"),
    "silverm": ("SILVERM", "MCX"),
    "silver": ("SILVERM", "MCX"),
    "copper": ("COPPER", "MCX"),
    "aluminium": ("ALUMINIUM", "MCX"),
    "zinc": ("ZINC", "MCX"),
    "natgasmini": ("NATGASMINI", "MCX"),
    "natgas": ("NATGASMINI", "MCX"),
    "crudeoilm": ("CRUDEOILM", "MCX"),
    "crude": ("CRUDEOILM", "MCX"),
}


async def _reply(chat_id: str, text: str):
    """Send a reply message."""
    url = API_BASE.format(token=settings.telegram_bot_token) + "/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })


async def _handle_command(chat_id: str, command: str):
    """Route command to handler."""
    cmd = command.strip().lower().lstrip("/")

    if cmd == "help":
        await _reply(chat_id, (
            "<b>Elder Trading Bot Commands</b>\n\n"
            "/status — All assets overview\n"
            "/pos — Open positions + P&L\n"
            "/funds — Balance & equity\n"
            "/signals — Recent signals\n"
            "/kill — Activate kill switch\n\n"
            "<b>Asset detail:</b>\n"
            "/nifty /banknifty /goldm /silverm\n"
            "/copper /aluminium /zinc\n"
            "/natgas /crude"
        ))

    elif cmd == "status":
        # Get from pipeline
        from app.pipeline import pipeline_manager
        summaries = pipeline_manager.get_all_summaries()
        lines = [f"<b>\U0001f4ca System Status \u2014 {len(summaries)} assets</b>\n"]
        for a in summaries:
            tide = a.get("tide", "-")
            grade = a.get("grade", "-")
            ltp = a.get("ltp")
            ltp_s = f"\u20b9{ltp:,.2f}" if ltp else "-"
            emoji = "\U0001f7e2" if tide == "BULLISH" else "\U0001f534" if tide == "BEARISH" else "\u26aa"
            lines.append(f"{emoji} <b>{a['symbol']}</b> {ltp_s} | {tide} | Grade {grade}")
        await _reply(chat_id, "\n".join(lines))

    elif cmd == "pos":
        from app.database import async_session
        from app.models.trade import Position
        from sqlalchemy import select
        async with async_session() as s:
            result = await s.execute(select(Position).where(Position.status == "OPEN"))
            positions = result.scalars().all()
        if not positions:
            await _reply(chat_id, "\U0001f4ed No open positions")
        else:
            lines = [f"<b>\U0001f4c8 Open Positions ({len(positions)})</b>\n"]
            for p in positions:
                pnl = p.unrealized_pnl or 0
                emoji = "\U0001f7e2" if pnl >= 0 else "\U0001f534"
                lines.append(
                    f"{emoji} <b>{p.symbol}</b> {p.direction} x{p.quantity}\n"
                    f"   Entry: \u20b9{p.entry_price:,.2f} | LTP: \u20b9{(p.current_price or p.entry_price):,.2f}\n"
                    f"   PnL: \u20b9{pnl:,.2f} | Stop: \u20b9{(p.stop_price or 0):,.2f}"
                )
            await _reply(chat_id, "\n".join(lines))

    elif cmd == "funds":
        from app.database import async_session
        from app.pipeline import db_persistence as db
        async with async_session() as s:
            equity = await db.get_current_equity(s, user_id=None)
        from app.models.trade import Position
        from sqlalchemy import select
        async with async_session() as s:
            result = await s.execute(select(Position).where(Position.status == "OPEN"))
            utilized = sum(abs(p.quantity * p.entry_price) for p in result.scalars().all())
        available = equity - utilized
        await _reply(chat_id, (
            f"<b>\U0001f4b0 Funds</b>\n\n"
            f"Net Equity: <b>\u20b9{equity:,.2f}</b>\n"
            f"Available: \u20b9{available:,.2f}\n"
            f"Utilized: \u20b9{utilized:,.2f}"
        ))

    elif cmd == "signals":
        from app.database import async_session
        from app.pipeline import db_persistence as db
        async with async_session() as s:
            signals = await db.load_recent_signals(s, limit=5)
        if not signals:
            await _reply(chat_id, "\U0001f4ed No recent signals")
        else:
            lines = ["<b>\U0001f4e1 Recent Signals</b>\n"]
            for sig in signals:
                lines.append(
                    f"{'\U0001f7e2' if sig['direction']=='LONG' else '\U0001f534'} "
                    f"<b>{sig['symbol']}</b> {sig['direction']} "
                    f"Score: {sig['score']}% | Entry: \u20b9{sig.get('entry_price',0):,.2f} | "
                    f"Status: {sig['status']}"
                )
            await _reply(chat_id, "\n".join(lines))

    elif cmd == "kill":
        from app.pipeline import pipeline_manager
        await pipeline_manager.activate_kill_switch("Telegram command")
        await _reply(chat_id, "\U0001f6a8 <b>KILL SWITCH ACTIVATED</b>\nAll trading halted.")

    elif cmd in SYMBOL_MAP:
        symbol, exchange = SYMBOL_MAP[cmd]
        from app.pipeline import pipeline_manager
        session = pipeline_manager.get_session(symbol, exchange)
        if not session or not session.active:
            await _reply(chat_id, f"\u274c {symbol} not tracked")
            return
        a = session.get_summary()
        al = session.alignment
        tide = a.get("tide", "-")
        wave = al.get("wave", "-")
        action = al.get("action", "WAIT")
        conf = al.get("confidence", 0)
        grade = a.get("grade", "-")
        ltp = a.get("ltp")

        s1_status = al.get("s1_status", "-")
        s2_status = al.get("s2_status", "-")
        s3_status = al.get("s3_status", "-")
        s1_price = al.get("s1_price")
        s2_price = al.get("s2_price")
        s3_price = al.get("s3_price")

        emoji = "\U0001f7e2" if tide == "BULLISH" else "\U0001f534" if tide == "BEARISH" else "\u26aa"

        if ltp:
            text = (
                f"{emoji} <b>{symbol}</b> ({exchange})\n"
                f"LTP: <b>\u20b9{ltp:,.2f}</b>\n\n"
            )
        else:
            text = f"{emoji} <b>{symbol}</b>\n\n"

        text += (
            f"Tide: <b>{tide}</b> | Wave: {wave}\n"
            f"Action: <b>{action}</b> | Conf: {conf}%\n"
            f"Grade: <b>{grade}</b>\n\n"
            f"<b>Screen Price Points:</b>\n"
            f"S1: {'\u2705' if s1_status=='aligned' else '\u27a1\ufe0f' if s1_status=='possible' else '\u23f3'} "
            f"{'\u20b9'+f'{s1_price:,.2f}' if s1_price else '-'}\n"
            f"S2: {'\u2705' if s2_status=='aligned' else '\u27a1\ufe0f' if s2_status=='possible' else '\u23f3'} "
            f"{'\u20b9'+f'{s2_price:,.2f}' if s2_price else '-'}\n"
            f"S3: {'\u2705' if s3_status=='aligned' else '\u27a1\ufe0f' if s3_status=='possible' else '\u23f3'} "
            f"{'\u20b9'+f'{s3_price:,.2f}' if s3_price else '-'}"
        )
        await _reply(chat_id, text)

    else:
        await _reply(chat_id, f"\u2753 Unknown command: /{cmd}\nType /help for available commands")


async def start_bot_polling():
    """Long-poll Telegram for commands. Runs as background task."""
    if not settings.telegram_bot_token:
        logger.info("Telegram bot token not set — command bot disabled")
        return

    logger.info("Telegram command bot starting...")
    url = API_BASE.format(token=settings.telegram_bot_token) + "/getUpdates"
    offset = 0

    while True:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, params={"offset": offset, "timeout": 25})
                if resp.status_code == 200:
                    data = resp.json()
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        msg = update.get("message", {})
                        text = msg.get("text", "")
                        chat_id = str(msg.get("chat", {}).get("id", ""))

                        # Only respond to commands (starts with /)
                        if text.startswith("/") and chat_id:
                            try:
                                await _handle_command(chat_id, text)
                            except Exception as e:
                                logger.warning("Bot command error: {}", e)
                                await _reply(chat_id, f"\u26a0\ufe0f Error: {str(e)[:100]}")
        except Exception as e:
            logger.debug("Bot poll error: {}", e)
            await asyncio.sleep(5)

        await asyncio.sleep(POLL_INTERVAL)
