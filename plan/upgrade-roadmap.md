# Elder Trading System — Upgrade Roadmap (72 → 90+)

## Current Score: 72/100
## Target Score: 90/100

---

## Phase 1: Performance & Latency (72 → 78)
**Goal**: Reduce end-to-end latency from 550ms to <100ms

### 1.1 Remove running bar throttle (500ms → 0ms)
- websocketManager.ts: remove 500ms throttle on running_bar
- Use requestAnimationFrame batching instead of time-based throttle
- Only update store once per animation frame (16ms cap)

### 1.2 Delta updates for WebSocket
- Backend: send only changed fields `{close: 23150, volume: 500}` not full bar
- Frontend: merge delta into existing running bar

### 1.3 Incremental EMA computation
- Add `update_incremental(new_bar)` to EMA indicator
- On bar close: compute next EMA from prev EMA + new close (O(1))
- Fall back to full recalc only on first load

---

## Phase 2: UI/UX Upgrade (78 → 84)
**Goal**: Bloomberg-class interactivity

### 2.1 Keyboard shortcuts
- B = Buy, S = Sell, C = Cancel all
- 1-5 = Switch timeframe (1m, 5m, 15m, 1h, 1d)
- Cmd+K = Quick symbol search
- Esc = Back to dashboard

### 2.2 Chart interactivity
- Entry/stop/target lines draggable on chart
- Click chart to set price → auto-fill order form
- Right-click context menu (Buy here, Sell here, Set alert)

### 2.3 Performance dashboard
- Equity curve chart
- Win rate, avg win/loss, profit factor
- R-multiple distribution
- Monthly P&L heatmap
- Drawdown tracking

### 2.4 Configurable layout
- Drag-and-resize dashboard panels
- Save layout to localStorage
- Multiple layout presets (Trading, Analysis, Overview)

---

## Phase 3: Portfolio Risk (84 → 88)
**Goal**: Portfolio-level awareness

### 3.1 Correlation matrix
- Compute 30-day rolling correlation between all 9 assets
- Block new trades that increase portfolio correlation > 0.7
- Visual correlation heatmap on dashboard

### 3.2 Sector/asset class grouping
- Group: NFO Indices, MCX Metals, MCX Energy
- Max exposure per group (e.g., 40% in metals)
- Show group exposure on dashboard

### 3.3 Dynamic position sizing
- Kelly criterion or volatility-adjusted sizing
- Reduce size after losing streak (anti-martingale)
- Increase size in low-volatility environments

---

## Phase 4: Production Hardening (88 → 92)
**Goal**: Production-grade resilience

### 4.1 Health check system
- /api/health returns detailed component status
- Auto-restart pipeline on deadlock detection
- Prometheus metrics endpoint

### 4.2 Audit trail
- Log every order action to separate audit table
- Include: who, when, what, why (signal_id reference)
- SEBI compliance-ready format

### 4.3 Database upgrade path
- Migration framework (Alembic)
- PostgreSQL option for production
- Automated daily backups

### 4.4 Error resilience
- Circuit breaker pattern on broker calls
- Retry budget (max 3 retries per minute per endpoint)
- Graceful degradation (show stale data, don't crash)

---

## Implementation Priority

| Phase | Effort | Impact | Score Gain |
|-------|--------|--------|------------|
| 1. Performance | 1 day | High | +6 |
| 2. UI/UX | 2-3 days | High | +6 |
| 3. Portfolio Risk | 1-2 days | Medium | +4 |
| 4. Production | 1-2 days | Medium | +4 |

**Start with Phase 1** — highest impact per effort.
