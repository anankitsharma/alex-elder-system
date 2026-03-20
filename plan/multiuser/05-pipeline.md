# Phase 5: Per-User Pipeline + Risk Management

## Architecture: Shared Data Layer + Per-User Execution Layer

```
SHARED DATA LAYER (one instance per symbol)
┌──────────────────────────────────────────┐
│  MarketFeed → CandleBuilder → IndicatorEngine  │
│  Writes to: candles table, indicators dict      │
│  NO user concept — pure market data             │
└──────────────────────┬───────────────────┘
                       │ candle_complete event
                       ▼
PER-USER EXECUTION LAYER (one instance per user×symbol)
┌──────────────────────────────────────────┐
│  UserPipelineSession (user_id + symbol)  │
│  ├─ TripleScreen analysis                │
│  ├─ AlertStateManager (per-user)         │
│  ├─ CircuitBreaker (per-user equity)     │
│  ├─ PositionSizer (per-user equity)      │
│  ├─ TradeExecutor (per-user broker)      │
│  └─ Notifications (per-user channels)    │
└──────────────────────────────────────────┘
```

## New File: `backend/app/pipeline/shared_data.py`

```python
"""Shared market data layer — candles + indicators for all users.

One SharedDataSession per tracked symbol. Receives ticks, builds candles,
computes indicators. Multiple UserPipelineSessions subscribe to its output.
"""

class SharedDataSession:
    """Manages shared market data for a single symbol."""

    def __init__(self, symbol: str, exchange: str, token: str):
        self.symbol = symbol
        self.exchange = exchange
        self.token = token

        # Candle buffers + builders (same as current AssetSession)
        self.candle_buffers: dict[str, pd.DataFrame] = {}
        self.candle_builders: dict[str, CandleBuilder] = {}
        self.indicators: dict[str, dict] = {}
        self._engines: dict[str, IndicatorEngine] = {}

        # Subscribers: user_id -> callback
        self._subscribers: dict[int, callable] = {}

    def subscribe(self, user_id: int, callback):
        self._subscribers[user_id] = callback

    def unsubscribe(self, user_id: int):
        self._subscribers.pop(user_id, None)

    async def on_candle_complete(self, timeframe, candle):
        """After candle closes + indicators computed, notify all subscribers."""
        for user_id, callback in self._subscribers.items():
            await callback(timeframe, candle, self.indicators)
```

## Refactored `PipelineManager`

```python
class PipelineManager:
    def __init__(self):
        # Shared data sessions: "NIFTY:NFO" -> SharedDataSession
        self._shared: dict[str, SharedDataSession] = {}

        # Per-user execution sessions: (user_id, "NIFTY:NFO") -> UserPipelineSession
        self._user_sessions: dict[tuple[int, str], UserPipelineSession] = {}

    async def start_tracking(self, user_id: int, symbol: str, exchange: str):
        key = f"{symbol}:{exchange}"

        # Create shared data session if not exists (first user to track this symbol)
        if key not in self._shared:
            shared = SharedDataSession(symbol, exchange, token)
            await shared.start()  # Load history, build candles
            self._shared[key] = shared

        # Create per-user execution session
        user_key = (user_id, key)
        if user_key not in self._user_sessions:
            user_session = UserPipelineSession(user_id, symbol, exchange, self._shared[key])
            await user_session.start()  # Load user's positions, init risk
            self._user_sessions[user_key] = user_session

        # Subscribe user to shared data events
        self._shared[key].subscribe(user_id, user_session.on_data_update)

    def on_tick(self, tick_data):
        """Route tick to shared data session (not per-user)."""
        token = str(tick_data.get("token", ""))
        # Find shared session by token
        for key, shared in self._shared.items():
            if shared.token == token:
                shared.on_tick(tick_data)
                break
```

## Per-User Session: `UserPipelineSession`

Extracted from current `AssetSession` — only the user-specific parts:

```python
class UserPipelineSession:
    """Per-user execution layer for a single symbol."""

    def __init__(self, user_id, symbol, exchange, shared: SharedDataSession):
        self.user_id = user_id
        self.symbol = symbol
        self.exchange = exchange
        self._shared = shared  # Reference to shared data

        # Per-user state
        self._alert_mgr = AlertStateManager()
        self._circuit_breaker = CircuitBreaker(...)
        self._signal_lock = asyncio.Lock()
        self._exit_initiated: set[int] = set()
        self.alignment: dict = {...}
        self.latest_analysis: Optional[dict] = None

    async def on_data_update(self, timeframe, candle, indicators):
        """Called when shared data layer has new candle + indicators."""
        # Read indicators from shared layer
        # Run TripleScreen analysis (per-user dead zones, thresholds)
        # Check signals through per-user risk gate
        # Execute through per-user broker session
```

## Circuit Breaker + Position Sizer

Already per-AssetSession (from our earlier fix). Just need to pass `user_id` to equity lookups:

```python
# In UserPipelineSession._init_circuit_breaker():
async with async_session() as session:
    month_start = await db.get_month_start_equity(session, user_id=self.user_id)
    self._circuit_breaker.set_month_start_equity(month_start)

# In _process_signal():
async with async_session() as session:
    account_equity = await db.get_current_equity(session, user_id=self.user_id)
```

## Resource Efficiency

For N users tracking the same symbol:
- **Before multi-user**: 1 CandleBuilder + 1 IndicatorEngine + 1 TripleScreen + 1 risk gate
- **After multi-user**: 1 CandleBuilder + 1 IndicatorEngine + N TripleScreen + N risk gates

Indicator computation (the expensive part) happens once. Signal evaluation (cheap) happens N times. This scales well to 10+ users.

## Stop Loss / Target Monitoring

`_check_stop_losses()` queries positions from DB filtered by `user_id`. Each UserPipelineSession checks its own user's positions against the shared price data.
