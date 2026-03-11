# Indicator Correctness Audit — Python vs Pine Script

## Summary

All 10 indicators audited against their Pine Script originals (where available) and Elder's book specifications. One issue found and fixed: Force Index EMA seed inconsistency.

## Audit Results

| # | Indicator | Pine Script Ref | Status | Notes |
|---|-----------|-----------------|--------|-------|
| 1 | EMA-13/22 | `ema.txt` (v6) | CORRECT | SMA seed + alpha=2/(n+1), smoothing MA types match |
| 2 | MACD(12,26,9) | `macd.txt` (v6) | CORRECT | EMA/SMA configurable, 4-color histogram matches exactly |
| 3 | Force Index | `efi_13.txt` (v6) | FIXED | EMA seed was first-value instead of SMA seed; now consistent |
| 4 | Impulse System | `impulse_pine.txt` (v3) | CORRECT | `ema[0]>ema[1] AND hist[0]>hist[1]` = green, exact match |
| 5 | SafeZone | `elder_safezone.txt` (v3) | CORRECT | Penetration avg, 3-bar min/max, progressive carry all match |
| 6 | Elder-Ray | (no Pine ref) | CORRECT | Bull=High-EMA, Bear=Low-EMA per Elder's book |
| 7 | Value Zone | (no Pine ref) | CORRECT | EMA-13/EMA-26 channel per Elder's specification |
| 8 | AutoEnvelope | (no Pine ref) | CORRECT | EMA-22 +/- 2.7*SD(100), population SD (ddof=0) |
| 9 | Thermometer | (no Pine ref) | CORRECT | max(H-prevH, prevL-L, 0), EMA smoothed |
| 10 | MACD Divergence | (no Pine ref) | CORRECT | Zero-crossing mandatory, peak/trough detection correct |

## Detailed Findings

### Force Index EMA Seed (FIXED)
- **Before**: `_calculate_ema()` in `force_index.py` seeded with first valid value directly
- **After**: Uses SMA of first `length` valid values as seed (consistent with all other indicators)
- **Impact**: Output starts at bar `length` instead of bar 1; slightly different initial values but converges to same series
- **All 10 indicators now use consistent SMA-seed EMA initialization**

### SafeZone Plot Offset (INFO)
- Pine Script plots `longvs[1]` and `shortvs[1]` (1-bar lag for protective stops)
- Our Python returns current bar's value (no lag)
- This is correct — the lag is a display convention, not a computation difference

### EMA Initialization: SMA Seed vs First-Value Seed
- TradingView's `ta.ema()` behavior is debated; some sources claim SMA seed, others first-value
- All our indicators consistently use SMA seed (standard financial industry approach)
- This ensures cross-indicator consistency (Impulse = EMA + MACD, both use same EMA)

## Per-Screen Chart Overlay Mapping

Based on Elder's Triple Screen methodology:

### Screen 1 — Weekly (Tide)
**Purpose**: Identify market tide direction
- Main chart: Candlesticks + EMA-13 + Impulse coloring
- Subchart: MACD histogram (slope = tide direction)
- Backend: `screen=1` -> computes only ema13, macd, impulse

### Screen 2 — Daily (Wave)
**Purpose**: Find entry timing using oscillators
- Main chart: Candlesticks + EMA-13 + EMA-22 + SafeZone + Impulse coloring
- Subchart 1: MACD histogram + line + signal
- Subchart 2: Force Index (FI-2 histogram + FI-13 line)
- Subchart 3: Elder-Ray (Bull/Bear Power)
- Backend: `screen=2` -> computes all Screen 2 indicators

### Screen 3 — Intraday (Ripple)
**Purpose**: Precision entry with trailing stops
- Main chart: Candlesticks + EMA-13 + SafeZone + Impulse coloring
- Subchart: Force Index (FI-2 only, entry timing)
- Backend: `screen=3` -> computes only ema13, fi_2, impulse, safezone
