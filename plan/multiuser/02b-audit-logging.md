# Phase 2B: Audit Logging

## Why

SEBI requires: "sound audit trail for all API orders and trades" with "identification of actual user and user-id" retained for **at least 5 years**.

Even without regulatory pressure, audit logs are essential for a multi-user system where one user's actions could affect shared resources.

## What Gets Logged

### Critical Events (ALWAYS logged)

| Category | Events | Details Captured |
|----------|--------|------------------|
| **Auth** | Login, logout, failed login, password change | user_id, IP, user_agent, success/failure |
| **Orders** | Create, modify, cancel, fill, reject | full order details (symbol, direction, qty, price, type), before/after state |
| **Positions** | Open, close (stop/target/EOD/flip/manual) | entry/exit price, P&L, reason |
| **Risk** | Circuit breaker trip/reset, risk setting change | old value → new value, who changed |
| **Mode** | PAPER→LIVE switch, LIVE→PAPER | who approved, who was switched |
| **Users** | Create, disable, role change, approve live | who did it, what changed |
| **Config** | System config change | key, old value, new value |
| **Pipeline** | Start/stop tracking | symbol, user_id |

### Informational Events (logged but lower priority)

| Category | Events |
|----------|--------|
| **Signals** | Signal generated, signal suppressed (dedup/risk) |
| **Notifications** | Alert sent, alert failed, alert queued |
| **Feed** | WebSocket connect/disconnect, feed stale |

## Database Schema

### `audit_logs` table

```sql
CREATE TABLE audit_logs (
    id            BIGSERIAL PRIMARY KEY,
    timestamp     TIMESTAMP NOT NULL DEFAULT NOW(),
    user_id       INTEGER REFERENCES users(id),     -- NULL for system events
    action        VARCHAR(100) NOT NULL,             -- 'order:create', 'user:approve_live', etc.
    category      VARCHAR(50) NOT NULL,              -- 'auth', 'trading', 'risk', 'admin', 'system'
    resource_type VARCHAR(50),                       -- 'order', 'position', 'user', 'config'
    resource_id   INTEGER,                           -- ID of affected record
    details       JSONB,                             -- Before/after values, extra context
    ip_address    VARCHAR(45),                       -- IPv4 or IPv6
    user_agent    VARCHAR(500),
    severity      VARCHAR(10) DEFAULT 'INFO'         -- INFO, WARNING, CRITICAL
);

-- Indexes for common queries
CREATE INDEX idx_audit_timestamp ON audit_logs(timestamp);
CREATE INDEX idx_audit_user ON audit_logs(user_id);
CREATE INDEX idx_audit_action ON audit_logs(action);
CREATE INDEX idx_audit_category ON audit_logs(category);
CREATE INDEX idx_audit_resource ON audit_logs(resource_type, resource_id);

-- Partition by month for performance (PostgreSQL)
-- ALTER TABLE audit_logs PARTITION BY RANGE (timestamp);
```

## Implementation

### New File: `backend/app/audit.py`

```python
"""Audit logging service.

Usage:
    from app.audit import audit_log

    await audit_log(
        user_id=user.id,
        action="order:create",
        category="trading",
        resource_type="order",
        resource_id=order.id,
        details={"symbol": "NIFTY", "direction": "BUY", "quantity": 65},
        request=request,  # FastAPI Request object (for IP/user_agent)
    )
"""

from datetime import datetime
from typing import Optional
from fastapi import Request
from loguru import logger
from app.database import async_session


async def audit_log(
    action: str,
    category: str,
    user_id: Optional[int] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    details: Optional[dict] = None,
    request: Optional[Request] = None,
    severity: str = "INFO",
):
    """Write an audit log entry to the database."""
    ip = None
    ua = None
    if request:
        ip = request.client.host if request.client else None
        ua = request.headers.get("user-agent", "")[:500]

    try:
        from app.models.audit import AuditLog
        async with async_session() as session:
            entry = AuditLog(
                timestamp=datetime.utcnow(),
                user_id=user_id,
                action=action,
                category=category,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details,
                ip_address=ip,
                user_agent=ua,
                severity=severity,
            )
            session.add(entry)
            await session.commit()
    except Exception as e:
        # Audit logging must never break the main flow
        logger.warning("Audit log write failed: {}", e)
```

### Where to add audit calls

```python
# api/auth.py — login
await audit_log(user_id=user.id, action="auth:login", category="auth", request=request)

# api/auth.py — failed login
await audit_log(action="auth:login_failed", category="auth",
                details={"email": req.email}, request=request, severity="WARNING")

# api/trading.py — place order
await audit_log(user_id=user.id, action="order:create", category="trading",
                resource_type="order", resource_id=order.id,
                details={"symbol": sym, "direction": dir, "qty": qty, "price": price})

# api/admin.py — approve live trading
await audit_log(user_id=admin.id, action="user:approve_live", category="admin",
                resource_type="user", resource_id=target_user.id,
                details={"target_user": target_user.email}, severity="CRITICAL")

# asset_session.py — circuit breaker trip
await audit_log(user_id=self.user_id, action="risk:circuit_breaker_trip", category="risk",
                details={"reason": reason, "exposure_pct": pct}, severity="CRITICAL")

# asset_session.py — position closed by stop
await audit_log(user_id=self.user_id, action="position:closed", category="trading",
                resource_type="position", resource_id=pos.id,
                details={"reason": "STOP_LOSS", "pnl": pnl, "exit_price": price})
```

### FastAPI Middleware for Request Logging (optional, high-volume)

```python
# Logs every API request — useful for debugging but generates many rows
@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    response = await call_next(request)
    # Only log non-GET requests (mutations) to reduce volume
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        user_id = getattr(request.state, "user_id", None)
        await audit_log(
            user_id=user_id,
            action=f"api:{request.method.lower()}:{request.url.path}",
            category="api",
            details={"status_code": response.status_code},
            request=request,
        )
    return response
```

## Admin Audit Log Viewer

### API Endpoint

```python
@router.get("/api/admin/audit-logs", dependencies=[Depends(RequireRole(Role.ADMIN))])
async def get_audit_logs(
    category: str = None,
    user_id: int = None,
    action: str = None,
    since: str = None,        # ISO date
    limit: int = 100,
    offset: int = 0,
):
    """Query audit logs with filters. Admin+ only."""
```

### Frontend UI (`/admin/audit`)
```
┌──────────────────────────────────────────────────────────────────────────┐
│  Audit Log                                    [Filter ▼] [Export CSV]   │
│                                                                          │
│  Time                User        Action              Details             │
│  ────────────────────────────────────────────────────────────────────── │
│  2026-03-21 10:15    Admin       auth:login           IP: 192.168.1.5   │
│  2026-03-21 10:16    Admin       pipeline:start       NIFTY:NFO         │
│  2026-03-21 10:32    Raj Kumar   order:create         BUY NIFTY x65     │
│  2026-03-21 10:45    Raj Kumar   position:closed      STOP_LOSS -₹1200  │
│  2026-03-21 11:00    Admin       user:approve_live    → Priya Singh     │
│  2026-03-21 11:01    SYSTEM      risk:cb_trip         Raj 6.2% exposure │
└──────────────────────────────────────────────────────────────────────────┘
```

## Retention

- **5 years minimum** per SEBI requirements
- Use PostgreSQL partitioning by month for performance
- Archive old partitions to cold storage after 1 year
- For SQLite (dev): periodic export to CSV, keep DB under 1GB

## Volume Estimate (2-10 users)

| Event Type | Per User/Day | Total (10 users) |
|------------|-------------|-------------------|
| Login/logout | 2 | 20 |
| Orders | 5-20 | 200 |
| Position events | 5-10 | 100 |
| Signal evaluations | 50-200 | 2,000 |
| Risk events | 1-5 | 50 |
| **Total** | | **~2,500 rows/day** |

At 2,500 rows/day × 365 days × 5 years = **~4.5M rows**. PostgreSQL handles this trivially.
