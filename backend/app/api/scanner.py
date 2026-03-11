"""Scanner API endpoints — instrument search and listing."""

from fastapi import APIRouter, Query

from app.broker.instruments import (
    download_scrip_master,
    filter_nse_equity,
    filter_nfo,
    filter_mcx,
    symbol_to_token_map,
)

router = APIRouter(prefix="/api/scanner", tags=["scanner"])


def _clean_symbol(symbol: str) -> str:
    """Remove -EQ suffix for display."""
    return symbol.replace("-EQ", "") if symbol.endswith("-EQ") else symbol


@router.get("/instruments")
async def list_instruments(
    exchange: str = Query("NSE", description="Exchange: NSE, NFO, MCX"),
    search: str = Query("", description="Search filter on symbol/name"),
    limit: int = Query(50, description="Max results"),
):
    """List instruments with optional search filter."""
    df = await download_scrip_master()

    if exchange == "NSE":
        filtered = filter_nse_equity(df)
    elif exchange == "NFO":
        filtered = filter_nfo(df)
    elif exchange == "MCX":
        filtered = filter_mcx(df)
    else:
        filtered = df[df["exch_seg"] == exchange]

    if search:
        search_upper = search.upper()
        filtered = filtered[
            filtered["symbol"].str.upper().str.contains(search_upper, na=False)
            | filtered["name"].str.upper().str.contains(search_upper, na=False)
        ]

    results = filtered.head(limit)[["token", "symbol", "name", "exch_seg", "lotsize", "tick_size"]].to_dict(orient="records")

    # Clean up symbols for frontend display
    for r in results:
        r["display_symbol"] = _clean_symbol(r.get("symbol", ""))

    return {"instruments": results, "count": len(results), "exchange": exchange}


@router.get("/token-map")
async def get_token_map(exchange: str = Query("NSE")):
    """Get symbol → token mapping for an exchange."""
    df = await download_scrip_master()
    mapping = symbol_to_token_map(df, exchange)
    return {"map": mapping, "count": len(mapping), "exchange": exchange}


@router.get("/nifty500")
async def get_nifty500_tokens():
    """Get tokens for NIFTY 500 stocks (all NSE equity instruments)."""
    df = await download_scrip_master()
    nse_eq = filter_nse_equity(df)
    instruments = nse_eq[["token", "symbol", "name"]].to_dict(orient="records")
    for inst in instruments:
        inst["display_symbol"] = _clean_symbol(inst.get("symbol", ""))
    return {"instruments": instruments, "count": len(instruments)}
