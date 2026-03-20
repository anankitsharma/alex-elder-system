# Phase 3: Add user_id to Per-User Tables

## Schema Changes

### Add `user_id` column to existing tables

Every table that holds user-specific data gets a `user_id` foreign key.

```sql
-- Orders
ALTER TABLE orders ADD COLUMN user_id INTEGER REFERENCES users(id);
CREATE INDEX idx_orders_user ON orders(user_id);

-- Positions
ALTER TABLE positions ADD COLUMN user_id INTEGER REFERENCES users(id);
CREATE INDEX idx_positions_user ON positions(user_id);

-- Trades
ALTER TABLE trades ADD COLUMN user_id INTEGER REFERENCES users(id);
CREATE INDEX idx_trades_user ON trades(user_id);

-- Signals
ALTER TABLE signals ADD COLUMN user_id INTEGER REFERENCES users(id);
CREATE INDEX idx_signals_user ON signals(user_id);

-- Portfolio Risk
ALTER TABLE portfolio_risk ADD COLUMN user_id INTEGER REFERENCES users(id);
CREATE INDEX idx_portfolio_risk_user ON portfolio_risk(user_id);
```

### Tables that stay shared (NO user_id)

- `instruments` — stock metadata
- `candles` — OHLCV market data
- `rollover_history` — contract events
- `config` — system-level settings

### Model changes

**`models/trade.py`** — add to Order, Position, Trade:
```python
user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
```

**`models/signal.py`** — add to Signal:
```python
user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
```

**`models/config.py`** — add to PortfolioRisk:
```python
user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
```

## Query Changes in `db_persistence.py`

Every query on per-user tables must filter by `user_id`. This is the highest-risk change — missing a filter leaks data across users.

### Pattern: Add `user_id` parameter to all per-user functions

```python
# Before:
async def load_open_positions_by_symbol(session, symbol):
    stmt = select(Position).where(
        and_(Position.symbol == symbol, Position.status == "OPEN")
    )

# After:
async def load_open_positions_by_symbol(session, symbol, user_id: int):
    stmt = select(Position).where(
        and_(Position.symbol == symbol, Position.status == "OPEN", Position.user_id == user_id)
    )
```

### Functions to update (all in `db_persistence.py`)

| Function | Add user_id param | Filter by user_id |
|----------|------------------|-------------------|
| `save_signal()` | Yes (in data dict) | N/A (insert) |
| `load_recent_signals()` | Yes | Yes |
| `save_order()` | Yes (in data dict) | N/A (insert) |
| `load_pending_orders()` | Yes | Yes |
| `update_order_fill()` | No (lookup by order_id, already scoped) | No |
| `save_position()` | Yes (in data dict) | N/A (insert) |
| `load_open_positions()` | Yes | Yes |
| `load_open_positions_by_symbol()` | Yes | Yes |
| `close_position()` | No (lookup by position_id, already scoped) | No |
| `update_position_stop()` | No (lookup by position_id) | No |
| `load_month_trades()` | Yes | Yes |
| `get_or_create_portfolio_risk()` | Yes | Yes |
| `update_portfolio_equity()` | Yes (via get_or_create) | Yes |
| `get_current_equity()` | Yes | Yes |
| `get_month_start_equity()` | Yes | Yes |

### Functions that stay unchanged (shared data)

- `get_or_create_instrument()` — shared
- `save_candles()` — shared
- `load_candles()` — shared
- `save_rollover()` — shared
- `load_continuous_candles()` — shared

## Safety: Audit Query

After implementation, run this query to find any per-user table queries missing the user_id filter:

```sql
-- Should return 0 rows if all per-user data is properly filtered
SELECT 'orders' as tbl, count(*) FROM orders WHERE user_id IS NULL
UNION ALL
SELECT 'positions', count(*) FROM positions WHERE user_id IS NULL
UNION ALL
SELECT 'trades', count(*) FROM trades WHERE user_id IS NULL
UNION ALL
SELECT 'signals', count(*) FROM signals WHERE user_id IS NULL;
```

## Migration Strategy for Existing Data

Existing data (from single-user era) gets assigned to user_id=1 (the initial admin user):

```sql
UPDATE orders SET user_id = 1 WHERE user_id IS NULL;
UPDATE positions SET user_id = 1 WHERE user_id IS NULL;
UPDATE trades SET user_id = 1 WHERE user_id IS NULL;
UPDATE signals SET user_id = 1 WHERE user_id IS NULL;
UPDATE portfolio_risk SET user_id = 1 WHERE user_id IS NULL;

-- Then make user_id NOT NULL
ALTER TABLE orders ALTER COLUMN user_id SET NOT NULL;
-- etc.
```
