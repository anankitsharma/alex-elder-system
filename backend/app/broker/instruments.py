"""Instrument master — download and manage Angel One scrip master data."""

import json
from datetime import datetime
from pathlib import Path
from loguru import logger

import httpx
import pandas as pd
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import Instrument

SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
CACHE_DIR = Path(__file__).resolve().parents[2] / "data"
CACHE_FILE = CACHE_DIR / "scrip_master.json"

# Exchange code mapping for WebSocket subscription
EXCHANGE_MAP = {
    "NSE": 1,
    "NFO": 2,
    "BSE": 3,
    "MCX": 5,
}


async def download_scrip_master(force: bool = False) -> pd.DataFrame:
    """Download Angel One scrip master JSON. Caches locally for the day."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Use cache if exists and is from today
    if not force and CACHE_FILE.exists():
        mtime = datetime.fromtimestamp(CACHE_FILE.stat().st_mtime)
        if mtime.date() == datetime.now().date():
            logger.info("Using cached scrip master from {}", mtime)
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            return pd.DataFrame(data)

    logger.info("Downloading scrip master from Angel One...")
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(SCRIP_MASTER_URL)
        resp.raise_for_status()
        data = resp.json()

    CACHE_FILE.write_text(json.dumps(data), encoding="utf-8")
    logger.info("Scrip master downloaded: {} instruments", len(data))
    return pd.DataFrame(data)


def filter_nse_equity(df: pd.DataFrame) -> pd.DataFrame:
    """Filter for NSE equity (cash) segment."""
    return df[
        (df["exch_seg"] == "NSE") & (df["symbol"].str.endswith("-EQ"))
    ].copy()


def filter_nfo(df: pd.DataFrame) -> pd.DataFrame:
    """Filter for NSE F&O segment."""
    return df[df["exch_seg"] == "NFO"].copy()


def filter_mcx(df: pd.DataFrame) -> pd.DataFrame:
    """Filter for MCX commodities segment."""
    return df[df["exch_seg"] == "MCX"].copy()


def lookup_token(df: pd.DataFrame, symbol: str, exchange: str = "NSE") -> str | None:
    """Find the Angel One token for a given symbol and exchange.

    For NSE equity: looks up '{symbol}-EQ'.
    For NFO/MCX futures: finds the best futures contract (earliest expiry >= 7 days).
    """
    if exchange == "NSE":
        search = f"{symbol}-EQ"
        match = df[(df["exch_seg"] == "NSE") & (df["symbol"] == search)]
        if match.empty:
            return None
        return str(match.iloc[0]["token"])

    # For derivatives exchanges (NFO, MCX) — find best futures contract
    match = df[
        (df["exch_seg"] == exchange)
        & (df["name"] == symbol)
        & (df["symbol"].str.contains("FUT", na=False))
    ]

    if match.empty:
        # Fallback: any matching name on the exchange
        match = df[(df["exch_seg"] == exchange) & (df["name"] == symbol)]
        if match.empty:
            return None
        return str(match.iloc[0]["token"])

    # Select best futures contract: earliest expiry with enough days left
    # MCX metals need more buffer (near-expiry contracts have price distortion)
    today = datetime.now()
    min_expiry_days = 15 if exchange == "MCX" else 7
    best = None

    for _, row in match.iterrows():
        expiry_str = row.get("expiry")
        if not expiry_str:
            continue
        try:
            expiry_date = datetime.strptime(str(expiry_str), "%d%b%Y")
        except (ValueError, TypeError):
            continue
        days_left = (expiry_date - today).days
        if days_left >= min_expiry_days:
            if best is None or expiry_date < best[1]:
                best = (str(row["token"]), expiry_date, row.get("symbol", ""))

    if best:
        logger.debug("Selected futures contract: {} (token={}, expiry={})",
                     best[2], best[0], best[1].strftime("%Y-%m-%d"))
        return best[0]

    # If no contract >= 7 days, take the nearest available
    if not match.empty:
        return str(match.iloc[0]["token"])
    return None


def symbol_to_token_map(df: pd.DataFrame, exchange: str = "NSE") -> dict[str, str]:
    """Build a symbol → token mapping for an exchange segment."""
    if exchange == "NSE":
        filtered = filter_nse_equity(df)
        return {
            row["symbol"].replace("-EQ", ""): str(row["token"])
            for _, row in filtered.iterrows()
        }
    filtered = df[df["exch_seg"] == exchange]
    return {
        row["symbol"]: str(row["token"])
        for _, row in filtered.iterrows()
    }


async def sync_instruments_to_db(session: AsyncSession, df: pd.DataFrame):
    """Sync scrip master data into the instruments table."""
    count = 0
    for _, row in df.iterrows():
        exch = row.get("exch_seg", "")
        if exch not in EXCHANGE_MAP:
            continue

        token = str(row["token"])
        symbol = row.get("symbol", "")
        name = row.get("name", "")

        # Determine segment
        if exch == "NSE" and symbol.endswith("-EQ"):
            segment = "EQ"
        elif exch == "NFO":
            segment = "FUT" if "FUT" in symbol else "OPT"
        elif exch == "MCX":
            segment = "COM"
        else:
            segment = "EQ"

        # Check if exists
        existing = await session.execute(
            select(Instrument).where(
                Instrument.token == token,
                Instrument.exchange == exch,
            )
        )
        if existing.scalar_one_or_none():
            continue

        inst = Instrument(
            token=token,
            symbol=symbol,
            name=name,
            exchange=exch,
            segment=segment,
            lot_size=int(row.get("lotsize", 1) or 1),
            tick_size=float(row.get("tick_size", 0.05) or 0.05),
            expiry=row.get("expiry", None) or None,
            strike=float(row["strike"]) if row.get("strike") and float(row.get("strike", 0)) > 0 else None,
            option_type=None,  # Parse from symbol if needed
        )
        session.add(inst)
        count += 1

        if count % 5000 == 0:
            await session.flush()

    await session.commit()
    logger.info("Synced {} new instruments to database", count)
