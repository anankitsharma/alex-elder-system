# Alexander Elder — Complete Trading Methodology

## 1. The Three M's Framework

Elder's entire trading philosophy rests on three pillars:

- **Mind** (Psychology): Developing discipline, avoiding emotional trading, understanding behavioral traps
- **Method** (Trading Tactics): Using charts, indicators, and systematic approaches to find trades
- **Money** (Risk Management): Protecting capital with position sizing and stop-loss rules

---

## 2. The Triple Screen Trading System

First published in **Futures Magazine in 1986**. Addresses the fundamental problem: trend-following indicators work in trending markets but give false signals in ranges, while oscillators work in ranges but fail in trends. Triple Screen combines both.

### Timeframe Hierarchy (Factor of 5)

| Screen | Timeframe | Purpose |
|--------|-----------|---------|
| Screen 1 (Long-term) | Weekly | Identify the "tide" (major trend direction) |
| Screen 2 (Intermediate) | Daily | Find "waves" (pullbacks within trend) |
| Screen 3 (Short-term) | 4-Hour / Intraday | Pinpoint exact entry ("ripples") |

Alternative timeframe combinations:
- Day traders: 60-min / 10-min / 2-min
- Position traders: Monthly / Weekly / Daily

### Screen 1 — Trend Identification
- **Primary Indicator**: MACD Histogram on the weekly chart (or the slope of a weekly EMA)
- **Alternative**: Slope of the 13-week EMA
- **Rule**: Only trade in the direction indicated by Screen 1
  - MACD-H rising (even if below zero) = bullish tide → look for long trades only
  - MACD-H falling (even if above zero) = bearish tide → look for short trades only

### Screen 2 — Identifying Counter-Trend Pullbacks
- **Indicators** (choose one): Force Index (2-day EMA), Elder-Ray, Stochastic, Williams %R
- **Rule for longs**: When Screen 1 is bullish, wait for daily oscillator to enter oversold (pullback within uptrend)
- **Rule for shorts**: When Screen 1 is bearish, wait for daily oscillator to enter overbought (rally within downtrend)

### Screen 3 — Entry Timing
- **Method**: Trailing buy-stop technique
- **For longs**: Place a buy-stop one tick above the high of the previous day. Trail it down day by day until triggered or abandoned.
- **For shorts**: Place a sell-stop one tick below the low of the previous day. Trail it up day by day.
- **Alternative**: Use support/resistance levels on short-term charts for precise entries

---

## 3. The Impulse System

Introduced in **"Come Into My Trading Room" (2002)**. Identifies inflection points where a trend speeds up or slows down. Uses color-coded price bars.

### Components
- **13-period EMA** (identifies trend direction)
- **MACD Histogram** with settings (12, 26, 9) (measures momentum)

### Color-Coding Rules

| Color | EMA Condition | MACD-H Condition | Meaning |
|-------|---------------|------------------|---------|
| **Green** | Rising (> previous bar) | Rising (> previous bar) | Bulls in control — trend accelerating up |
| **Red** | Falling (< previous bar) | Falling (< previous bar) | Bears in control — trend accelerating down |
| **Blue** | Mixed signals | Mixed signals | Neither side dominant — transition zone |

### Trading Rules
- **Green bars**: PROHIBIT selling / shorting
- **Red bars**: PROHIBIT buying / going long
- **Blue bars**: Allow trading in either direction
- **Philosophy**: "Enter cautiously but exit fast" — the opposite of amateur behavior

### Multi-Timeframe Application
- Apply Impulse System on both long-term and intermediate timeframes
- A 65-period EMA on daily chart (5 × 13) can substitute for the weekly 13-EMA
- Alternatively, MACD(1, 65, 1) on daily chart approximates the weekly trend

---

## 4. Value Zone

The space between two exponential moving averages:
- **EMA(13)** — fast line
- **EMA(26)** — slow line (some sources cite EMA(22))

**Trading Rule**: When prices dip into the Value Zone during an uptrend → buying opportunity. When prices rally into the Value Zone during a downtrend → shorting opportunity. Moves too far from the Value Zone are considered overbought/oversold.

---

## 5. Entry Signals (Summary)

1. **Triple Screen Long Entry**:
   - Screen 1: Weekly MACD-H slope is rising (bullish tide)
   - Screen 2: Daily oscillator (FI 2-day, Stochastic, or Elder-Ray) reaches oversold
   - Screen 3: Place trailing buy-stop above previous day's high

2. **Impulse System Entry**:
   - Green bars on both weekly and daily charts
   - Enter when daily Impulse turns green after blue (transition to bullish)

3. **MACD-H Divergence Entry**:
   - Bullish divergence with zero-line cross between bottoms
   - Enter when MACD-H ticks up from second shallower bottom

4. **Value Zone Entry**:
   - Price dips into zone between EMA(13) and EMA(26) during uptrend
   - Confirmed by Impulse System not being red

---

## 6. Exit Signals

1. **Profit Targets**: Upper AutoEnvelope line (for longs), lower line (for shorts)
2. **Trailing Stop**: Move stop to 1.7 SD (inner channel) once price nears 2.7 SD target
3. **Impulse Exit**: Exit longs when daily Impulse turns red; exit shorts when green
4. **Chandelier Exit**: Trailing stop based on ATR from highest high
5. **Elder's philosophy**: Exit fast when signals deteriorate — "Enter cautiously but exit fast"

---

## 7. SafeZone Stops

Introduced in "Come Into My Trading Room." Uses **Directional Movement (DM)** instead of ATR.

### Parameters
- Lookback Period: **22 days** (default)
- Multiplication Factor: **2.0 to 4.0** (default 2.5)
- Trend Filter: EMA(22) or EMA(63)

### Calculation for Uptrend (Long) Stops
```
1. Identify downward directional movement: -DM = Yesterday's Low - Today's Low (when positive)
2. Count all -DM days in the lookback period
3. Average -DM = Sum of all -DM values / Count of -DM days
4. Today's Stop = Yesterday's Low - (Factor × Average -DM)
5. Only move stops UP — apply maximum of last 3 days' stops
```

### Calculation for Downtrend (Short) Stops
```
1. Identify upward directional movement: +DM = Today's High - Yesterday's High (when positive)
2. Count all +DM days in the lookback period
3. Average +DM = Sum of all +DM values / Count of +DM days
4. Today's Stop = Yesterday's High + (Factor × Average +DM)
5. Only move stops DOWN — apply minimum of last 3 days' stops
```

---

## 8. Risk Management

### The 2% Rule (Position-Level Risk)
Never risk more than **2% of account equity** on any single trade.

```
Maximum Risk per Trade = Account Equity × 0.02
Position Size = Maximum Risk / (Entry Price - Stop Loss Price)
```

Example: ₹10,00,000 account → max risk = ₹20,000 per trade. If stop is ₹50 from entry, max position = 400 shares.

### The 6% Rule (Portfolio-Level Risk)
Stop opening new positions when **total outstanding risk** (sum of all open position risks + realized losses this month) reaches **6% of account equity** (measured at prior month-end).

- 2% rule protects from "shark bites" (single large losses)
- 6% rule protects from "piranhas" (death by a thousand cuts)

### Practical Application
- Track risk of each open position = (Entry - Stop) × Shares
- Track cumulative realized losses for the current month
- When combined total ≥ 6% of prior month-end equity → stop trading until next month

---

## 9. Trade Grading & Record Keeping

Elder considers record keeping the **single most important factor** in trading success.

### Trade Grading System
```
Grade = (Exit Price - Entry Price) / (Upper Channel - Lower Channel) × 100%
```
- **A-trade**: Captured ≥ 30% of channel width
- Uses the AutoEnvelope channel width on the day of entry

### Journal Requirements
Every trade must have a written trade plan with entry, target, stop, and risk calculated BEFORE execution. Post-trade review grades the execution.

---

## 10. Elder's Books (Key References)

| Title | Year | Key Content |
|-------|------|-------------|
| **Trading for a Living** | 1993 | Original classic — Triple Screen, Three M's |
| **Come Into My Trading Room** | 2002 | Impulse System, SafeZone Stops, 2%/6% rules |
| **The New Trading for a Living** | 2014 | Major update — added new studies, templates, modern tools |
| **Two Roads Diverged** | 2012 | Deep dive on MACD-H divergence trading |
| **Sell and Sell Short** | 2008/2011 | Selling methodology, AutoEnvelope, Chandelier Exit |
| **The New High–New Low Index** | 2012 | NH-NL as market breadth indicator |

---

## 11. Current Methodology (2024-2025)

Elder's core system has remained consistent since the 2014 update. Current emphasis:
1. Triple Screen with Impulse System as the primary framework
2. Value Zone (EMA 13/26) for entry identification
3. AutoEnvelope for profit targets and trade grading
4. NH-NL Index for market breadth timing
5. SafeZone stops or ATR-based stops for risk control
6. 2%/6% rules for money management
7. Rigorous trade journaling and grading
8. Added emphasis on scanning methodologies and options strategies
