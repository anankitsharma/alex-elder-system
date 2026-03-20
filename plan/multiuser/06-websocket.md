# Phase 6: Per-User WebSocket Routing

## Current State

- `_pipeline_clients: list[WebSocket]` — flat list, all events to all clients
- `_clients: list[WebSocket]` — raw tick broadcast to all
- No authentication on WebSocket endpoints

## Target Architecture

```python
# Per-user connection tracking
_user_connections: dict[int, list[WebSocket]] = {}  # user_id -> [ws1, ws2, ...]

# Per-user symbol subscriptions
_user_subscriptions: dict[int, set[str]] = {}  # user_id -> {"NIFTY:NFO", ...}
```

## Changes to `ws/market_stream.py`

### WebSocket Authentication

```python
@router.websocket("/ws/pipeline")
async def pipeline_websocket(websocket: WebSocket):
    # Authenticate before accepting
    from app.middleware.auth import get_ws_user
    user = await get_ws_user(websocket)
    if not user:
        await websocket.close(code=4001, reason="Authentication required")
        return

    await websocket.accept()

    # Register connection for this user
    if user.id not in _user_connections:
        _user_connections[user.id] = []
    _user_connections[user.id].append(websocket)
```

### Event Broadcasting

Events split into two categories:

**Shared events** (market data — sent to ALL users subscribed to that symbol):
- `candle` — new candle bar
- `running_bar` — in-progress bar
- `indicators` — indicator values
- `pipeline_status` — session status
- `heartbeat`

**Private events** (per-user — sent ONLY to owning user):
- `signal` — triple screen signal (per-user risk gate may differ)
- `order` — trade execution
- `order_rejected`
- `position_closed`
- `trailing_stop_updated`
- `trade_alert`

```python
async def broadcast_shared_event(symbol: str, event: dict):
    """Send market data event to all users subscribed to this symbol."""
    for user_id, subs in _user_subscriptions.items():
        if f"{symbol}" in subs or any(symbol in s for s in subs):
            for ws in _user_connections.get(user_id, []):
                try:
                    await ws.send_json(event)
                except Exception:
                    pass

async def broadcast_user_event(user_id: int, event: dict):
    """Send private event to a specific user's connections."""
    for ws in _user_connections.get(user_id, []):
        try:
            await ws.send_json(event)
        except Exception:
            pass
```

### Client Messages

Client-to-server messages now scoped by user:

```python
# Client sends:
{"action": "start_tracking", "symbol": "NIFTY", "exchange": "NFO"}

# Server processes with user context:
async def handle_pipeline_message(user_id, msg):
    action = msg.get("action")
    if action == "start_tracking":
        await pipeline_manager.start_tracking(user_id, msg["symbol"], msg["exchange"])
        _user_subscriptions.setdefault(user_id, set()).add(f"{msg['symbol']}:{msg['exchange']}")
```

## Frontend Changes

### `websocketManager.ts`

```typescript
// Add token to WebSocket URL
const token = localStorage.getItem('access_token');
const wsUrl = `${WS_BASE}/ws/pipeline?token=${token}`;
this.pipelineWs = new WebSocket(wsUrl);
```

### Handle 4001 auth error

```typescript
this.pipelineWs.onclose = (event) => {
    if (event.code === 4001) {
        // Auth failed — redirect to login
        window.location.href = '/login';
        return;
    }
    // Normal reconnect logic
};
```

## `/ws/market` Endpoint

The raw tick endpoint (`/ws/market`) can stay unauthenticated for now — it only receives market data (no private information). Or add optional auth if you want to restrict access.

## Connection Cleanup

When a user disconnects:
```python
# Remove from connection list
_user_connections[user_id].remove(websocket)
if not _user_connections[user_id]:
    del _user_connections[user_id]
    # If user has no connections, optionally stop their pipeline sessions
```
