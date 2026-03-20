# Multi-User Elder Trading System — Master Plan

## Executive Summary

Convert the single-user Elder Trading System into a multi-user platform where:
- **Market data is shared** — one feed connection, one candle store, one set of indicators
- **Everything else is per-user** — broker accounts, positions, orders, risk settings, alerts, trading mode

Target: **2-10 users** on a single server. No Kubernetes, no microservices, no message brokers needed.

## Architecture Principle

```
                    SHARED LAYER                         PER-USER LAYER
              ┌─────────────────────┐     ┌──────────────────────────────────────┐
              │  Angel One Feed     │     │  User A                             │
              │  (1 connection)     │     │  ├─ Broker Session (own API keys)   │
              │         │           │     │  ├─ Pipeline Sessions (own signals) │
              │  CandleBuilder      │────>│  ├─ Risk Gate (own CB + sizer)     │
              │  (per symbol)       │     │  ├─ Positions / Orders / Trades    │
              │         │           │     │  ├─ Telegram (own chat_id)         │
              │  Indicator Engine   │     │  └─ WebSocket (filtered events)    │
              │  (per timeframe)    │     ├──────────────────────────────────────┤
              │         │           │     │  User B                             │
              │  Candle DB (shared) │────>│  ├─ Broker Session (own API keys)   │
              │  Instrument DB      │     │  ├─ Pipeline Sessions (own signals) │
              └─────────────────────┘     │  ├─ ...                            │
                                          └──────────────────────────────────────┘
```

## What's Shared (Same for ALL users)

| Component | Location | Why Shared |
|-----------|----------|------------|
| Market feed WebSocket | `broker/websocket_feed.py` | One connection to Angel One feed (rate limited) |
| CandleBuilder | `pipeline/candle_builder.py` | OHLCV bars are market facts, not user opinions |
| Candle storage | `candles` table | Historical data is universal |
| Instrument metadata | `instruments` table | Stock names, tokens, exchanges |
| Indicator computation | `pipeline/indicator_engine.py` | EMA, MACD, etc. are math on shared candles |
| Rollover history | `rollover_history` table | Contract events are exchange-level |
| Holiday calendar | `pipeline/holidays.py` | Exchange holidays apply to all |

## What's Per-User (Isolated per user)

| Component | Current Location | What Changes |
|-----------|-----------------|--------------|
| Broker credentials | `.env` (single set) | Encrypted in `user_broker_credentials` table |
| Broker session | `angel` singleton | Per-user `AngelClient` instances |
| Trading mode | `settings.trading_mode` | Per-user PAPER/LIVE toggle |
| Positions | `positions` table | Add `user_id` column |
| Orders | `orders` table | Add `user_id` column |
| Trades | `trades` table | Add `user_id` column |
| Signals | `signals` table | Add `user_id` column |
| Portfolio risk | `portfolio_risk` table | Add `user_id` column |
| Circuit breaker | Singleton in `asset_session.py` | Per-user instance |
| Position sizer | Created per signal | Uses per-user equity |
| Account equity | Hardcoded 100k (now DB) | Per-user `portfolio_risk` record |
| Alert channels | `.env` (global Telegram) | Per-user `chat_id` / webhook |
| Alert preferences | None | Per-user priority/mute settings |
| Watchlist | Global settings | Per-user watchlist |
| WebSocket events | Broadcast to all | Filtered by user |
| Signal evaluation | `AssetSession` (global) | Per-user evaluation with own risk gate |

## Database Strategy

**Migrate SQLite to PostgreSQL** before adding multi-user. SQLite's database-level write lock will cause `database is locked` errors with concurrent users.

**Pattern**: Shared tables + `user_id` column (row-level filtering). For 2-10 users, this is simpler than schema-per-tenant or DB-per-tenant.

## Implementation Phases

| Phase | What | Plan File | Blocked By |
|-------|------|-----------|-----------|
| **Phase 1** | PostgreSQL migration + Alembic | `01-database.md` | Nothing |
| **Phase 2** | User model + JWT auth | `02-auth.md` | Phase 1 |
| **Phase 2A** | Roles, permissions, admin system | `02a-roles-permissions.md` | Phase 2 |
| **Phase 2B** | Audit logging | `02b-audit-logging.md` | Phase 2 |
| **Phase 3** | Add `user_id` to all per-user tables | `03-data-isolation.md` | Phase 2 |
| **Phase 4** | Per-user broker sessions | `04-broker-sessions.md` | Phase 2 |
| **Phase 5** | Per-user pipeline + risk | `05-pipeline.md` | Phase 3+4 |
| **Phase 6** | Per-user WebSocket routing | `06-websocket.md` | Phase 2 |
| **Phase 7** | Per-user notifications | `07-notifications.md` | Phase 3 |
| **Phase 8** | Frontend auth + admin UI | `08-frontend.md` | Phase 2 |
| **Checklist** | Migration + testing + security | `09-migration-checklist.md` | All phases |

See individual phase files for detailed plans.

## Key Design Decisions

### 1. Default User = Super Admin
The current single user becomes User #1 with `super_admin` role. All existing data (positions, orders, trades, signals) is assigned to this user during migration. Existing `.env` broker credentials are encrypted and stored for this user.

### 2. Four Fixed Roles (No Dynamic Role Creation)
For 2-10 users, hardcoded roles are simpler and safer than a role builder UI. Roles: `super_admin`, `admin`, `trader`, `viewer`. Each role inherits all permissions of roles below it.

### 3. PAPER-First, LIVE Requires Approval
New users start in PAPER mode. LIVE trading requires explicit Super Admin approval (logged in audit trail). This prevents accidental real-money trading.

### 4. Admin Can View Everything, Trade Nothing
Admin/Risk Manager can see all users' positions and P&L but cannot place orders on behalf of others. Only traders place their own orders.

### 5. Audit Everything
All mutations (orders, position changes, risk modifications, user management, mode switches) are logged with user_id, timestamp, IP, and before/after values. 5-year retention per SEBI requirements.

### 6. SEBI Compliance Notes
- Unique user-id per user on all orders/trades (Phase 3)
- 2FA on login (Phase 2 — TOTP or similar)
- Audit trail with 5-year retention (Phase 2B)
- If order frequency > 10/sec per user, exchange algo-ID required by April 2026
- No RIA/PMS registration needed if team trades own capital

## File Impact Summary

### New Files
```
backend/
  alembic/                          # DB migrations (Alembic)
  app/models/user.py                # User, UserBrokerCredentials, UserNotificationConfig
  app/models/audit.py               # AuditLog model
  app/api/auth.py                   # Login/register/me endpoints
  app/api/admin.py                  # User management, approve live, audit log viewer
  app/middleware/auth.py             # JWT validation, RequireRole, RequirePermission
  app/audit.py                      # audit_log() service function
  app/broker/session_manager.py     # Per-user AngelClient pool
  app/pipeline/shared_data.py       # Shared candle/indicator layer
  scripts/migrate_to_multiuser.py   # One-time migration script
frontend/
  src/app/login/page.tsx            # Login page
  src/app/admin/page.tsx            # Admin panel (user management, audit logs)
  src/lib/auth.ts                   # Token storage + refresh
  src/store/useAuthStore.ts         # Auth state slice
  src/components/admin/             # UserTable, AccessRequests, AuditViewer
```

### Modified Files (Major Changes)
```
backend/
  app/config.py                     # PostgreSQL URL, JWT secret
  app/database.py                   # asyncpg engine, Alembic support
  app/models/trade.py               # user_id on Order, Position, Trade
  app/models/signal.py              # user_id on Signal
  app/models/config.py              # user_id on PortfolioRisk
  app/pipeline/__init__.py          # Per-user PipelineManager
  app/pipeline/asset_session.py     # user_id, per-user CB/equity
  app/pipeline/db_persistence.py    # user_id filter on all queries
  app/ws/market_stream.py           # Auth + per-user broadcasts
  app/notifications/telegram.py     # Per-user chat_id routing
  app/api/trading.py                # user_id on all endpoints
  app/api/strategy.py               # user_id on pipeline/risk endpoints
  app/api/settings.py               # Per-user settings
  app/broker/angel_client.py        # Remove singleton, add factory
frontend/
  src/lib/api.ts                    # Authorization header
  src/lib/websocketManager.ts       # Token in WS handshake
  src/store/useTradingStore.ts      # User slice
  src/app/page.tsx                  # Auth guard
```

### Unchanged Files
```
backend/
  app/indicators/*                  # Pure math, no user concept
  app/strategy/*                    # Analysis logic, no user concept
  app/risk/*                        # Algorithms unchanged (just called per-user)
  app/pipeline/candle_builder.py    # Shared data layer
  app/pipeline/indicator_engine.py  # Shared computation
  app/pipeline/market_hours.py      # Exchange data
  app/pipeline/holidays.py          # Exchange data
  app/pipeline/utils.py             # Pure helpers
  app/api/charts.py                 # Shared candle data
  app/api/demo_data.py              # Demo generator
  app/broker/historical.py          # Shared historical data
  app/broker/instruments.py         # Shared instrument lookup
tests/
  test_golden_reference.py          # Indicator math tests (unchanged)
  test_timeframe_config.py          # Config tests (unchanged)
frontend/
  src/components/chart/*            # Chart rendering (unchanged)
```
