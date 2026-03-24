# Positional Trading + Gap Open Handling — Research & Plan

## Current State (What's Broken)

1. **EOD auto-close kills ALL positions** — even though Elder's Triple Screen is a swing/positional system that uses weekly + daily timeframes. Closing every day defeats the purpose.

2. **No gap handling** — if a signal forms at 15:25 and market opens with a 3% gap next morning, the system either misses the trade or enters at a terrible price.

3. **Product type is hardcoded** to CARRYFORWARD — correct for futures, but the EOD close then contradicts this by closing everything anyway.

## Solution Architecture

### Position Types

Each position should have a `position_type` field:

| Type | Behavior | When Used |
|------|----------|-----------|
| `INTRADAY` | Close before market end (3:20 for NSE, 23:25 for MCX) | Day trading, scalping |
| `POSITIONAL` | Carry overnight, close on exit signal | Triple Screen swing trades (default) |
| `DELIVERY` | Hold indefinitely (equity only) | Not used for futures |

**Default for Triple Screen: POSITIONAL** — the system should NOT close positions at EOD unless they're explicitly flagged as INTRADAY.

### EOD Close Logic (Fixed)

```
Current: Close ALL positions at EOD cutoff
Fixed:   Only close positions where position_type == "INTRADAY"
         POSITIONAL positions carry forward
         On Friday: optionally warn about weekend gap risk (no auto-close)
```

### Overnight Margin Handling

- **INTRADAY (MIS):** ~5-6% margin, auto-squared off by broker at 3:15 PM
- **POSITIONAL (NRML):** 12-15% SPAN + Exposure margin, carries forward
- **Our paper mode:** Track margin at entry_price × margin_pct (configurable per exchange)
- **Risk reduction:** Overnight positions should use 1% risk per trade instead of 2% (configurable)

### Gap Open Handling — Signal Queue

When a Triple Screen signal forms but market is about to close (or has closed):

```
1. Signal forms at 15:25 IST
2. Market closes at 15:30
3. Signal is QUEUED (not executed) with:
   - signal_price (entry level from Triple Screen)
   - stop_price (SafeZone level)
   - target_price (2:1 R:R)
   - max_gap_pct = 2% (configurable)
   - expiry = next market open + 15 minutes

4. Next morning at 9:15 IST:
   a. Load queued signals
   b. Get opening price
   c. Calculate gap: gap_pct = abs(open - signal_price) / signal_price
   d. If gap_pct > max_gap_pct → SKIP signal (too risky)
   e. If gap_pct <= max_gap_pct → Execute with ADJUSTED prices:
      - entry = open_price (not signal_price)
      - stop = recalculated from new entry (same distance or wider)
      - target = recalculated from new entry (same R:R)
      - position_size = recalculated (gap may widen effective stop)
```

### Gap-Adjusted Position Sizing

```python
# Original signal
signal_entry = 22800  # prev bar high
signal_stop = 22500   # SafeZone
risk_per_share = 300
shares = account_risk / risk_per_share  # 4000 / 300 = 13

# Gap open scenario
actual_open = 22950   # gap up +0.66%
adjusted_stop = actual_open - 300  # maintain same risk distance = 22650
# OR
adjusted_stop = 22500  # keep original stop → wider risk = 450
adjusted_shares = account_risk / 450  # 4000 / 450 = 8 (fewer shares)
```

**Rule: Always recalculate position size from actual entry, not signal entry.**

### Stop Loss Behavior Across Sessions

| Scenario | What Happens |
|----------|-------------|
| Stop at 100, opens at 98 (gap through) | Stop triggers at 98 (market order fill at open) |
| Stop at 100, opens at 102 (gap away) | Stop still active at 100, no change |
| Trailing stop at 105, closes at 108, opens at 103 | Stop still at 105, position survives |
| Trailing stop at 105, opens at 104 | Stop NOT hit (104 > 105 for SHORT, but depends on direction) |

**Key insight:** Stop-loss orders on exchange (GTT on Angel One) provide continuous protection, including at open. Our in-system stops only check every 2 seconds during market hours — they'll catch the gap at the first tick.

### Implementation Plan

**Phase 1: Position type + EOD fix**
- Add `position_type` field to Position model (INTRADAY/POSITIONAL)
- Default Triple Screen positions to POSITIONAL
- EOD close: only close INTRADAY positions
- Add config: `default_position_type = "POSITIONAL"`

**Phase 2: Signal queue for overnight signals**
- Add `queued_signals` table or status="QUEUED" on Signal model
- When signal forms < 10 min before close → queue instead of execute
- At market open (9:16 IST) → process queued signals with gap check
- Max gap filter: skip if gap > 2% of signal price (configurable)

**Phase 3: Gap-adjusted execution**
- Recalculate entry/stop/target from actual open price
- Recalculate position size with adjusted risk
- Log gap magnitude for analysis

**Phase 4: Overnight risk adjustments**
- Reduce position size for POSITIONAL trades (1% risk vs 2%)
- Wider stops for overnight holds (+50% ATR)
- Friday risk warning (optional: reduce size or skip new entries)

## Research Sources

- Freqtrade: No EOD close by default, all positions are implicitly positional
- Backtrader: Gap fills at open price (better or worse than limit)
- QuantConnect: 0.25% cash buffer for gap risk, `Schedule.On` for EOD close
- Angel One: CARRYFORWARD/NRML product type, AMO orders for overnight queue
- SEBI: Full SPAN + Exposure margin for CARRYFORWARD futures positions
