# Elder Trading System — Gaps Analysis

## Summary

10 gaps identified across indicators, tests, and infrastructure. Ordered by severity.

| # | Gap | Severity | Status |
|---|-----|----------|--------|
| 1 | No golden reference tests — all tests use synthetic Brownian motion | CRITICAL | DONE |
| 2 | SafeZone O(N^2) nested loops (`safezone.py:85-211`) — 12 inner loops per bar | HIGH | DONE |
| 3 | No per-timeframe indicator config — same params for 1m and 1d | HIGH | DONE |
| 4 | No cross-timeframe signal validation — Screen 1 tide not checked against Screen 2 | HIGH | DONE |
| 5 | AutoEnvelope ddof inconsistency — `ddof=1` at line 94 vs `ddof=0` elsewhere | MEDIUM | DONE |
| 6 | No indicator-to-indicator invariant tests (Impulse=green requires EMA up AND MACD-H up) | MEDIUM | DONE |
| 7 | E2E test timing — hardcoded `waitForTimeout()` causes flaky failures | MEDIUM | DONE |
| 8 | Elder Thermometer default period 22 vs Elder's recommended 13 | LOW | DONE |
| 9 | No streaming/incremental computation — full recalc on every candle | LOW | Deferred |
| 10 | API hardcodes indicator params — no frontend override possible | LOW | Partial |

---

## Gap Details

### 1. No Golden Reference Tests (CRITICAL) — DONE
- **Impact**: Cannot verify indicator correctness against known values
- **Remediation**: Created `tests/golden_data.py` with deterministic 50-bar dataset and `tests/test_golden_reference.py` with hand-computed expected values for all 10 indicators plus 6 cross-indicator invariant tests
- **Files**: `tests/golden_data.py`, `tests/test_golden_reference.py`

### 2. SafeZone O(N^2) Performance (HIGH) — DONE
- **Impact**: 12 inner loops per bar, each up to lookback=22 iterations
- **Remediation**: Replaced inner loops with prefix-sum arrays for O(1) window lookups. O(N) total complexity.
- **Files**: `backend/app/indicators/safezone.py`

### 3. No Per-Timeframe Indicator Config (HIGH) — DONE
- **Impact**: Same indicator params used for 1m and 1d charts
- **Remediation**: Created `timeframe_config.py` with screen-to-indicator mapping and asset-class-based timeframe selection. Added `screen` query param to `/api/indicators/compute`.
- **Files**: `backend/app/indicators/timeframe_config.py`, `backend/app/api/indicators.py`

### 4. No Cross-Timeframe Signal Validation (HIGH) — DONE
- **Impact**: Screen 1 impulse not checked against Screen 2 signals
- **Remediation**: Created `cross_timeframe_validator.py` with impulse conflict detection, screen alignment validation, and data timeframe verification. Integrated into `TripleScreenAnalysis.analyze()`.
- **Files**: `backend/app/strategy/cross_timeframe_validator.py`, `backend/app/strategy/triple_screen.py`

### 5. AutoEnvelope ddof Inconsistency (MEDIUM) — DONE
- **Impact**: `ddof=1` (sample SD) used instead of `ddof=0` (population SD) for channel width
- **Remediation**: Changed to `ddof=0` with configurable override
- **Files**: `backend/app/indicators/auto_envelope.py`

### 6. No Cross-Indicator Invariant Tests (MEDIUM) — DONE
- **Impact**: No verification that Impulse green <=> EMA rising AND MACD-H rising
- **Remediation**: 6 invariant tests added to `tests/test_golden_reference.py`
- **Files**: `tests/test_golden_reference.py`

### 7. E2E Test Timing (MEDIUM) — DONE
- **Impact**: Hardcoded `waitForTimeout()` causes flaky test failures
- **Remediation**: Created `frontend/e2e/helpers.ts` with `waitForDashboardReady()` and replaced timeouts with deterministic waits on API responses and DOM elements
- **Files**: `frontend/e2e/helpers.ts`, `frontend/e2e/dashboard.spec.ts`

### 8. Elder Thermometer Period (LOW) — DONE
- **Impact**: Default period 22 vs Elder's classic 13
- **Remediation**: Added docstring citing source, added `CLASSIC_PERIOD = 13` constant
- **Files**: `backend/app/indicators/elder_thermometer.py`

### 9. No Streaming/Incremental Computation (LOW) — Deferred
- **Impact**: Full recalculation on every new candle
- **Remediation**: Deferred to future optimization phase (event bus architecture)

### 10. API Hardcodes Indicator Params (LOW) — Partial
- **Impact**: Frontend cannot override indicator parameters
- **Remediation**: `screen` param added; full param override deferred to frontend redesign
