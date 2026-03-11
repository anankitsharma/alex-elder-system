# Elder Indicators — Complete Parameter & Formula Reference

## Quick Reference Table

| Indicator | Parameters | Formula |
|-----------|------------|---------|
| **EMA(13)** | Period: 13 | Standard EMA — Impulse System, Value Zone fast |
| **EMA(22)** | Period: 22 | SafeZone base, AutoEnvelope center (~1 month trading days) |
| **EMA(26)** | Period: 26 | Value Zone slow, EMA crossover with 13 |
| **EMA(65)** | Period: 65 | Daily proxy for weekly 13-EMA (5×13) |
| **MACD** | Fast:12, Slow:26, Signal:9 | MACD = EMA(12)-EMA(26); Signal = EMA(9) of MACD |
| **MACD Histogram** | — | MACD Line - Signal Line |
| **Force Index (short)** | EMA: 2 | FI(1) = (Close-PrevClose)×Volume → EMA(2) smoothed |
| **Force Index (long)** | EMA: 13 | FI(1) → EMA(13) smoothed |
| **Elder-Ray Bull Power** | EMA: 13 | High - EMA(13) |
| **Elder-Ray Bear Power** | EMA: 13 | Low - EMA(13) |
| **Impulse System** | EMA:13, MACD:12/26/9 | Green=both rising, Red=both falling, Blue=mixed |
| **SafeZone Stop** | Lookback:22, Factor:2.5 | Long: Low-(Factor×Avg -DM); Short: High+(Factor×Avg +DM) |
| **AutoEnvelope** | EMA:22, Width:2.7 SD, 100 bars | Upper=EMA(22)+2.7×StdDev; Lower=EMA(22)-2.7×StdDev |
| **Stochastic** | %K:14, %D:3, Slowing:3 | Overbought>80, Oversold<20 |
| **Williams %R** | Period: 14 | Overbought>-20, Oversold<-80 |
| **ATR** | Period: 14 | For stops: 2 ATR from entry |
| **NH-NL Index** | N/A | New 52-week Highs minus New 52-week Lows |
| **Euphoria/Depression** | 3 ATR from EMA(22) | Extreme profit-taking zones |

---

## Detailed Formulas

### 1. Exponential Moving Average (EMA)

```
Multiplier = 2 / (Period + 1)
EMA_today = (Close - EMA_yesterday) × Multiplier + EMA_yesterday
```

Elder uses these specific periods:
- **EMA(13)**: Fast line for Impulse System + Value Zone
- **EMA(22)**: SafeZone base + AutoEnvelope center (~1 month)
- **EMA(26)**: Value Zone slow line + MACD slow component
- **EMA(65)**: Daily proxy for weekly 13-EMA (5 × 13)
- **EMA(200)**: Long-term trend confirmation (some variants)

**EMA Crossover Signal**: 13-EMA crosses above 26-EMA = bullish; below = bearish

---

### 2. MACD and MACD Histogram

```
MACD Line = EMA(12) - EMA(26)
Signal Line = EMA(9) of MACD Line
MACD Histogram = MACD Line - Signal Line
```

**Key Signals**:
- **Bullish Divergence**: Price makes new low, MACD-H makes higher low. CRITICAL: MACD-H must cross above zero between the two lows ("breaking the back of the bear"). Buy: MACD-H ticks up from second, shallower bottom.
- **Bearish Divergence**: Price makes new high, MACD-H makes lower high. MACD-H must cross below zero between the two highs. Sell: MACD-H ticks down from second, lower peak.
- **Slope changes**: Used in Impulse System — rising = bullish momentum, falling = bearish

---

### 3. Force Index

```
Force Index(1) = (Close_today - Close_yesterday) × Volume
Force Index(N) = EMA(N) of Force Index(1)
```

**2-Day EMA** (Short-term oscillator — Screen 2 pullback finder):
- Uptrend: Buy when 2-day FI turns negative (pullback)
- Downtrend: Sell when 2-day FI turns positive (bounce)

**13-Day EMA** (Medium-term trend confirmer):
- Above zero = uptrend; Below zero = downtrend
- Divergences provide reversal warnings

---

### 4. Elder-Ray Index (Bull Power / Bear Power)

```
Bull Power = High - EMA(13)
Bear Power = Low - EMA(13)
```

**Long Entry**:
1. 13-EMA rising
2. Bear Power below zero BUT rising (bears weakening)
3. Bullish divergence in Bear Power strengthens signal
4. Best: Bear Power dips below zero then rises back

**Short Entry**:
1. 13-EMA falling
2. Bull Power above zero BUT falling (bulls weakening)
3. Bearish divergence in Bull Power strengthens signal

**Rule**: Only trade in direction of 13-EMA slope.

---

### 5. Impulse System

```
IF EMA(13) > EMA(13)_prev AND MACD_H > MACD_H_prev → GREEN (bulls)
IF EMA(13) < EMA(13)_prev AND MACD_H < MACD_H_prev → RED (bears)
OTHERWISE → BLUE (neutral)
```

- **Green**: Prohibit selling/shorting
- **Red**: Prohibit buying/going long
- **Blue**: Trade either direction

---

### 6. SafeZone Stops

**Long Stop (Uptrend)**:
```
For each bar in lookback (22 days):
  If Low_prev > Low_today: -DM = Low_prev - Low_today
  Else: -DM = 0

Average_neg_DM = Sum(-DM where -DM > 0) / Count(-DM > 0)
Raw_Stop = Low_yesterday - (Factor × Average_neg_DM)
Stop = MAX(Raw_Stop, Stop_prev1, Stop_prev2)  # Only moves up
```

**Short Stop (Downtrend)**:
```
For each bar in lookback (22 days):
  If High_today > High_prev: +DM = High_today - High_prev
  Else: +DM = 0

Average_pos_DM = Sum(+DM where +DM > 0) / Count(+DM > 0)
Raw_Stop = High_yesterday + (Factor × Average_pos_DM)
Stop = MIN(Raw_Stop, Stop_prev1, Stop_prev2)  # Only moves down
```

Default: Lookback=22, Factor=2.5

---

### 7. AutoEnvelope

```
Center = EMA(22)    # daily charts
Upper = EMA(22) + 2.7 × StdDev(Close, 100)
Lower = EMA(22) - 2.7 × StdDev(Close, 100)
Inner_Upper = EMA(22) + 1.7 × StdDev(Close, 100)   # for trailing stops
Inner_Lower = EMA(22) - 1.7 × StdDev(Close, 100)
```

**Design**: Channel lines must contain ~95% of all prices for past 2-3 months.

**Trading Rules**:
- Sell longs near upper channel (profit target)
- Cover shorts near lower channel (profit target)
- Recalculate at most once per week (daily charts)

**Trade Grading**:
```
Grade = (Sell - Buy) / (Upper - Lower) × 100%
A-trade = ≥ 30% of channel height
```

---

### 8. Stochastic Oscillator

```
%K = 100 × (Close - Low_14) / (High_14 - Low_14)
%D = SMA(3) of %K
Slow %K = %D
Slow %D = SMA(3) of Slow %K
```

Parameters: %K=14, %D=3, Slowing=3
Overbought: >80 | Oversold: <20

Elder uses this as Screen 2 oscillator to find pullbacks.

---

### 9. Williams %R

```
%R = -100 × (High_14 - Close) / (High_14 - Low_14)
```

Overbought: >-20 | Oversold: <-80
Functionally inverted Stochastic. Interchangeable with Stochastic for Screen 2.

---

### 10. ATR (Average True Range)

```
True Range = MAX(High-Low, |High-PrevClose|, |Low-PrevClose|)
ATR = EMA(14) of True Range
```

**Stop placement**: 2 ATR from current price.

---

### 11. NH-NL Index (New High–New Low)

```
NH-NL = Number of New 52-week Highs - Number of New 52-week Lows
```

Elder calls this the **"stock market's best leading indicator."**
- Tracks market breadth and internal strength
- Divergences between NH-NL and price indices signal major market turns

---

### 12. Euphoria/Depression Channel

```
Upper = EMA(22) + 3 × ATR(14)
Lower = EMA(22) - 3 × ATR(14)
```

Marks extreme zones where price rarely sustains positions outside.

---

## Libraries That Provide These Indicators

| Indicator | pandas-ta | TA-Lib | Custom Needed |
|-----------|-----------|--------|---------------|
| EMA | `ta.ema()` | `talib.EMA()` | No |
| MACD + Histogram | `ta.macd()` | `talib.MACD()` | No |
| Stochastic | `ta.stoch()` | `talib.STOCH()` | No |
| RSI | `ta.rsi()` | `talib.RSI()` | No |
| ATR | `ta.atr()` | `talib.ATR()` | No |
| Williams %R | `ta.willr()` | `talib.WILLR()` | No |
| Force Index | Compute from components | Compute from components | Partial |
| Elder-Ray | `ta.eri()` | Compute from components | Partial |
| Impulse System | — | — | **Yes** |
| SafeZone Stops | — | — | **Yes** |
| AutoEnvelope | — | — | **Yes** |
| Triple Screen | — | — | **Yes** |
| Divergence Detector | — | — | **Yes** |
