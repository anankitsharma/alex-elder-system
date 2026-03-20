# Elder Trading System — Admin & Multi-User Setup

## Default Admin Credentials

```
Username : admin
Email    : admin@elder.local
Password : admin123
Role     : super_admin
Mode     : PAPER
```

**Change the password immediately after first login.**

## Roles

| Role | Level | What They Can Do |
|------|-------|------------------|
| `super_admin` | 0 (highest) | Everything — manage users, approve LIVE trading, system config, audit logs |
| `admin` | 1 | View all users' positions/P&L, modify risk settings, reset circuit breaker |
| `trader` | 2 | Place/cancel orders, start/stop pipeline, view own data only |
| `viewer` | 3 (lowest) | Read-only — charts, signals, indicators, own portfolio |

## How to Start

```bash
# 1. Start backend (from backend/ directory)
cd backend
uvicorn app.main:app --reload --port 8000

# 2. Start frontend (from frontend/ directory)
cd frontend
npm run dev
```

Open `http://localhost:3001` — login form appears. Use admin credentials above.

## Creating New Users

Only `super_admin` can create users.

**Via API:**
```bash
# Login first to get JWT token
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123" | jq -r .access_token)

# Create a trader
curl -X POST http://localhost:8000/api/admin/users \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "trader1@example.com",
    "username": "trader1",
    "password": "secure-password",
    "full_name": "Raj Kumar",
    "role": "trader"
  }'
```

New users start in **PAPER mode** — they need admin approval to go LIVE.

## Live Trading Approval Flow

```
1. Trader requests:  POST /api/auth/request-live  (with their JWT)
2. Admin reviews:    GET  /api/admin/access-requests
3. Admin approves:   POST /api/admin/approve-live/{user_id}
   OR rejects:       POST /api/admin/reject-live/{user_id}
```

## API Auth

All API requests require JWT token:

```
Authorization: Bearer <token>
```

Get a token via `POST /api/auth/login` with username + password.

WebSocket connections pass token as query param:
```
ws://localhost:8000/ws/pipeline?token=<JWT>
```

## Key API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/auth/login` | POST | None | Login (returns JWT) |
| `/api/auth/me` | GET | Any | Current user profile |
| `/api/auth/request-live` | POST | Trader+ | Request LIVE trading access |
| `/api/admin/users` | GET | Admin+ | List all users |
| `/api/admin/users` | POST | Super Admin | Create new user |
| `/api/admin/users/{id}` | PUT | Super Admin | Update user role/settings |
| `/api/admin/approve-live/{id}` | POST | Super Admin | Approve LIVE trading |
| `/api/admin/reject-live/{id}` | POST | Super Admin | Reject with reason |
| `/api/admin/access-requests` | GET | Super Admin | List pending requests |
| `/api/admin/stats` | GET | Admin+ | System-wide statistics |
| `/api/strategy/pipeline/asset-settings` | GET | Any | Get per-asset mode settings |
| `/api/strategy/pipeline/asset-settings/{symbol}` | PUT | Trader+ | Toggle per-asset PAPER/LIVE |

## Per-Asset Trading Mode (PAPER/LIVE Toggle)

Each asset can independently be set to PAPER or LIVE mode. This allows a user to:
- Paper trade NIFTY while live trading GOLDM
- Test a new asset in PAPER before switching to LIVE
- Keep risky instruments in PAPER permanently

**How it works:**
1. Dashboard shows a **Mode badge** (PAPER/LIVE) next to each tracked asset
2. Click the badge to toggle between PAPER and LIVE
3. LIVE mode requires admin approval first (user must be `approved_for_live`)
4. The toggle takes effect immediately on the running pipeline

**Priority order:** Per-asset setting > User's global mode > System default

**API:**
```bash
# Toggle NIFTY to LIVE
curl -X PUT "http://localhost:8000/api/strategy/pipeline/asset-settings/NIFTY?exchange=NFO&trading_mode=LIVE&user_id=1" \
  -H "Authorization: Bearer $TOKEN"

# Toggle GOLDM back to PAPER
curl -X PUT "http://localhost:8000/api/strategy/pipeline/asset-settings/GOLDM?exchange=MCX&trading_mode=PAPER&user_id=1" \
  -H "Authorization: Bearer $TOKEN"
```

## Notification Setup (Per User)

Each user has their own Telegram/Discord channels. The admin's channels were migrated from `.env` during setup.

To add Telegram for a new user:
1. User sends `/start` to the Elder Trading bot
2. Note their `chat_id`
3. Admin updates via DB or future settings UI

## Database

- **Location**: `backend/elder_trading.db` (SQLite, dev)
- **Migrations**: Alembic (`backend/alembic/`)
- **Backup**: `backend/elder_trading.db.bak` (pre-migration snapshot)

To run migrations after schema changes:
```bash
cd backend
python -m alembic revision --autogenerate -m "description"
python -m alembic upgrade head
```

## Security Notes

- Passwords hashed with bcrypt (12 rounds)
- JWT tokens expire after 24 hours
- Broker credentials encrypted with Fernet (AES-128) if `CREDENTIAL_KEY` set in `.env`
- Audit log tracks all mutations (orders, user changes, risk modifications)
- Per SEBI: retain audit logs for 5 years minimum
