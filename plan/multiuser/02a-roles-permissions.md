# Phase 2A: Roles, Permissions & Admin System

## Role Hierarchy

```
SUPER_ADMIN (the current single user — system owner)
  │
  ├── Can do everything
  ├── Manage all users (create, disable, change roles)
  ├── Approve LIVE trading access
  ├── Modify system config
  ├── View all audit logs
  ├── Switch any user's trading mode
  │
ADMIN / RISK_MANAGER
  │
  ├── View ALL users' positions, orders, P&L (read-only)
  ├── Modify risk parameters (per-user or global)
  ├── Reset circuit breaker for any user
  ├── Cannot create/delete users or change system config
  │
TRADER
  │
  ├── Place/modify/cancel own orders
  ├── Start/stop own pipeline tracking
  ├── View own positions, trades, signals, P&L
  ├── Change own notification preferences
  ├── Cannot see other users' data
  ├── Cannot modify risk settings
  ├── Starts in PAPER mode — needs SUPER_ADMIN approval for LIVE
  │
VIEWER
  │
  ├── Read-only access to market data, charts, signals
  ├── View own portfolio (if any)
  ├── Cannot place orders or start pipeline
  └── Cannot change any settings
```

## Database Schema

### `roles` table
```sql
CREATE TABLE roles (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(50) UNIQUE NOT NULL,  -- 'super_admin', 'admin', 'trader', 'viewer'
    description TEXT,
    is_system   BOOLEAN DEFAULT FALSE,        -- System roles can't be deleted
    created_at  TIMESTAMP DEFAULT NOW()
);

-- Seed data (created on first migration)
INSERT INTO roles (name, description, is_system) VALUES
    ('super_admin', 'Full system control — manage users, config, approve live trading', TRUE),
    ('admin',       'Risk manager — view all positions, modify risk params, reset CB', TRUE),
    ('trader',      'Place orders, manage own pipeline, view own data', TRUE),
    ('viewer',      'Read-only access to market data and own portfolio', TRUE);
```

### `permissions` table
```sql
CREATE TABLE permissions (
    id       SERIAL PRIMARY KEY,
    name     VARCHAR(100) UNIQUE NOT NULL,  -- 'order:create', 'user:manage', etc.
    category VARCHAR(50) NOT NULL           -- 'trading', 'risk', 'admin', 'data'
);
```

### `role_permissions` junction table
```sql
CREATE TABLE role_permissions (
    role_id       INTEGER REFERENCES roles(id) ON DELETE CASCADE,
    permission_id INTEGER REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);
```

### Update `users` table
```sql
ALTER TABLE users ADD COLUMN role_id INTEGER REFERENCES roles(id) DEFAULT 3;  -- Default: trader
ALTER TABLE users ADD COLUMN approved_for_live BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN approved_by INTEGER REFERENCES users(id);
ALTER TABLE users ADD COLUMN approved_at TIMESTAMP;
ALTER TABLE users ADD COLUMN created_by INTEGER REFERENCES users(id);
```

## Permission Matrix

| Permission | Super Admin | Admin | Trader | Viewer |
|------------|:-----------:|:-----:|:------:|:------:|
| **Market Data** | | | | |
| `data:view` | Y | Y | Y | Y |
| `signals:view` | Y | Y | Y | Y |
| `indicators:view` | Y | Y | Y | Y |
| **Trading** | | | | |
| `order:create` | Y | - | Y | - |
| `order:modify` | Y | - | Y | - |
| `order:cancel` | Y | - | Y | - |
| `position:close` | Y | - | Y | - |
| **Pipeline** | | | | |
| `pipeline:start` | Y | Y | Y | - |
| `pipeline:stop` | Y | Y | Y | - |
| **Portfolio** | | | | |
| `portfolio:view_own` | Y | Y | Y | Y |
| `portfolio:view_all` | Y | Y | - | - |
| **Risk** | | | | |
| `risk:view` | Y | Y | Y | Y |
| `risk:modify` | Y | Y | - | - |
| `circuit_breaker:reset` | Y | Y | - | - |
| **User Management** | | | | |
| `user:create` | Y | - | - | - |
| `user:modify` | Y | - | - | - |
| `user:disable` | Y | - | - | - |
| `user:view_all` | Y | Y | - | - |
| **System** | | | | |
| `config:modify` | Y | - | - | - |
| `trading_mode:approve` | Y | - | - | - |
| `audit:view` | Y | Y | - | - |

## Implementation: FastAPI Dependency Injection

### `backend/app/middleware/auth.py` — additions

```python
from enum import Enum

class Role(str, Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    TRADER = "trader"
    VIEWER = "viewer"

# Role hierarchy: higher roles inherit all lower permissions
ROLE_HIERARCHY = {
    Role.SUPER_ADMIN: 0,  # Highest
    Role.ADMIN: 1,
    Role.TRADER: 2,
    Role.VIEWER: 3,        # Lowest
}

class RequireRole:
    """FastAPI dependency — check user has required role (or higher).

    Usage:
        @router.post("/orders", dependencies=[Depends(RequireRole(Role.TRADER))])
        async def create_order(user: User = Depends(get_current_user)):
            ...
    """
    def __init__(self, min_role: Role):
        self.min_role = min_role

    async def __call__(self, user: User = Depends(get_current_user)) -> User:
        user_role = user.role.name if user.role else "viewer"
        user_level = ROLE_HIERARCHY.get(user_role, 99)
        required_level = ROLE_HIERARCHY.get(self.min_role, 0)
        if user_level > required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user_role}' insufficient. Requires '{self.min_role.value}' or higher.",
            )
        return user


class RequirePermission:
    """Fine-grained permission check (for when role hierarchy isn't enough).

    Usage:
        @router.post("/risk/cb-reset", dependencies=[Depends(RequirePermission("circuit_breaker:reset"))])
    """
    def __init__(self, permission: str):
        self.permission = permission

    async def __call__(self, user: User = Depends(get_current_user)) -> User:
        # Load user's role → permissions from DB (cached)
        user_perms = await _get_user_permissions(user.id)
        if self.permission not in user_perms:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {self.permission}",
            )
        return user
```

### Endpoint examples

```python
# Anyone can view charts
@router.get("/api/charts/{symbol}")
async def get_chart(symbol: str, user: User = Depends(get_current_user)):
    ...

# Only traders+ can place orders
@router.post("/api/trading/order", dependencies=[Depends(RequireRole(Role.TRADER))])
async def place_order(req: OrderRequest, user: User = Depends(get_current_user)):
    ...  # user.id used for all DB operations

# Only admin+ can modify risk settings
@router.put("/api/strategy/risk-settings", dependencies=[Depends(RequireRole(Role.ADMIN))])
async def update_risk(req: RiskSettingsRequest, user: User = Depends(get_current_user)):
    ...

# Only super_admin can create users
@router.post("/api/admin/users", dependencies=[Depends(RequireRole(Role.SUPER_ADMIN))])
async def create_user(req: CreateUserRequest, user: User = Depends(get_current_user)):
    ...

# Only super_admin can approve live trading
@router.post("/api/admin/approve-live/{target_user_id}", dependencies=[Depends(RequireRole(Role.SUPER_ADMIN))])
async def approve_live_trading(target_user_id: int, user: User = Depends(get_current_user)):
    ...
```

## Default User (Migration from Single-User)

The existing single-user system becomes **User #1 (Super Admin)**:

```python
# backend/scripts/migrate_to_multiuser.py
"""
Run once during migration. Creates the admin user from current .env credentials.

Usage: python -m backend.scripts.migrate_to_multiuser
"""

async def migrate():
    # 1. Create super_admin role (if not exists)
    # 2. Create User #1 with:
    #    - email from .env or default "admin@elder.local"
    #    - password from CLI prompt
    #    - role = super_admin
    #    - trading_mode from current settings.trading_mode
    #    - approved_for_live = True
    # 3. Encrypt current .env broker creds → user_broker_credentials for user_id=1
    # 4. Set user_id=1 on all existing orders, positions, trades, signals
    # 5. Copy current telegram_chat_id → user_notifications for user_id=1
```

## Live Trading Approval Flow

```
1. Trader signs up → role=TRADER, trading_mode=PAPER, approved_for_live=FALSE

2. Trader uses system in PAPER mode (full functionality, no real money)

3. Trader requests LIVE access:
   POST /api/auth/request-live
   → Creates access_request record (status=PENDING)
   → Sends Telegram notification to all SUPER_ADMIN users

4. Super Admin reviews:
   GET /api/admin/access-requests  (list pending)
   → Sees trader's paper P&L history, trade count, days active

5. Super Admin approves:
   POST /api/admin/approve-live/{user_id}
   → Sets user.approved_for_live = TRUE
   → Sets user.trading_mode = "LIVE"
   → Logs in audit_logs
   → Sends Telegram notification to trader
   → Trader must still add their own broker credentials

6. OR Super Admin rejects:
   POST /api/admin/reject-live/{user_id}  {reason: "Need 30 more days paper trading"}
   → Logs rejection + reason
   → Sends Telegram notification to trader with reason
```

### `access_requests` table

```sql
CREATE TABLE access_requests (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER REFERENCES users(id),
    request_type  VARCHAR(50) NOT NULL,  -- 'live_trading', 'risk_override', 'role_upgrade'
    status        VARCHAR(20) DEFAULT 'PENDING',  -- PENDING, APPROVED, REJECTED
    reason        TEXT,                  -- Rejection reason or approval note
    requested_at  TIMESTAMP DEFAULT NOW(),
    reviewed_by   INTEGER REFERENCES users(id),
    reviewed_at   TIMESTAMP
);
```

## Admin UI Pages

### User Management (`/admin/users`)
```
┌──────────────────────────────────────────────────────────────┐
│  User Management                              [+ Add User]  │
│                                                              │
│  Name          Email              Role      Mode   Status    │
│  ─────────────────────────────────────────────────────────── │
│  Admin (you)   admin@elder.local  SUPER_ADMIN  LIVE  Active  │
│  Raj Kumar     raj@example.com    TRADER       PAPER Active  │
│  Priya Singh   priya@example.com  TRADER       LIVE  Active  │
│  Amit Viewer   amit@example.com   VIEWER       -     Active  │
│                                                              │
│  [Click row to edit role / disable / view positions]         │
└──────────────────────────────────────────────────────────────┘
```

### Access Requests (`/admin/requests`)
```
┌──────────────────────────────────────────────────────────────┐
│  Pending Access Requests                                     │
│                                                              │
│  Raj Kumar requests LIVE TRADING access                      │
│  Paper trading: 45 days | P&L: +₹12,340 | Win rate: 62%     │
│  Trades: 38 | Max drawdown: -₹3,200                         │
│                                                              │
│  [Approve]  [Reject]  [View Full History]                    │
└──────────────────────────────────────────────────────────────┘
```
