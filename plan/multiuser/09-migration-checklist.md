# Migration Checklist & Testing Strategy

## Pre-Migration Checklist

- [ ] Backup existing SQLite database
- [ ] Export current positions, orders, trades (for verification)
- [ ] Document current .env credentials (will become admin user's creds)
- [ ] Install PostgreSQL locally or via Docker
- [ ] Generate JWT secret: `openssl rand -hex 32`
- [ ] Generate Fernet encryption key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

## Phase 1 Verification (PostgreSQL)

- [ ] All 413 existing tests pass against PostgreSQL
- [ ] Candle data loads correctly
- [ ] Pipeline starts and processes ticks
- [ ] Paper trading works end-to-end
- [ ] Alembic migration baseline created

## Phase 2 Verification (Auth)

- [ ] POST /api/auth/register creates user
- [ ] POST /api/auth/login returns JWT
- [ ] GET /api/auth/me returns user profile with valid JWT
- [ ] All endpoints return 401 without JWT
- [ ] WebSocket rejects connection without token
- [ ] Token expiry works (re-login after 24h)
- [ ] Admin user created with existing .env credentials

## Phase 2A Verification (Roles & Permissions)

- [ ] 4 roles exist in DB: super_admin, admin, trader, viewer
- [ ] User #1 (migrated admin) has super_admin role
- [ ] Trader cannot access /api/admin/* endpoints (403)
- [ ] Viewer cannot place orders (403)
- [ ] Admin can view all users' positions but cannot place orders for them
- [ ] Super Admin can create new users with any role
- [ ] Role change logged in audit_logs
- [ ] Live trading approval flow works:
  - [ ] Trader requests live → creates access_request
  - [ ] Super Admin receives notification
  - [ ] Approval sets user.trading_mode = LIVE
  - [ ] Rejection sends reason to trader

## Phase 2B Verification (Audit Logging)

- [ ] Login event logged with IP and user_agent
- [ ] Failed login logged with severity=WARNING
- [ ] Order placement logged with full details
- [ ] Position close logged with P&L
- [ ] Circuit breaker trip logged with severity=CRITICAL
- [ ] Risk setting change logged with before/after values
- [ ] User creation / role change / live approval logged
- [ ] Admin can query audit logs with filters (category, user, date)
- [ ] Audit log entries cannot be deleted (no DELETE endpoint)
- [ ] Verify 5+ year retention plan documented

## Phase 3 Verification (Data Isolation)

- [ ] Create User A and User B
- [ ] User A places order → User B cannot see it
- [ ] User A has position → User B's position query returns empty
- [ ] User A's signals don't appear in User B's signal list
- [ ] Shared data (candles, instruments) accessible to both
- [ ] Existing data migrated to admin user (user_id=1)

## Phase 4 Verification (Broker Sessions)

- [ ] User can save broker credentials via UI
- [ ] Credentials encrypted in DB (verify raw column is gibberish)
- [ ] Broker session creates on first trade
- [ ] Session refreshes after TTL
- [ ] User without credentials → clear error message
- [ ] PAPER mode works without broker credentials

## Phase 5 Verification (Pipeline)

- [ ] User A starts tracking NIFTY → shared data session created
- [ ] User B starts tracking NIFTY → shares candle data, gets own signal evaluation
- [ ] User A's circuit breaker trips → User B can still trade
- [ ] User A's signal fires → only User A gets trade execution
- [ ] User A stops tracking → shared data stays (User B still tracking)
- [ ] Both users stop → shared data session cleaned up

## Phase 6 Verification (WebSocket)

- [ ] User A connects → receives only their events
- [ ] User A's order fills → only User A gets notification via WS
- [ ] Market data (candles) → both users receive for subscribed symbols
- [ ] User disconnects → connections cleaned up
- [ ] Token expires → WebSocket closes with 4001

## Phase 7 Verification (Notifications)

- [ ] User A sets Telegram chat_id → receives DM
- [ ] User B has no chat_id → no Telegram (no error)
- [ ] User A's trade → notification to User A only
- [ ] System startup → notification to admin only
- [ ] Daily summary → each user gets their own P&L

## Phase 8 Verification (Frontend)

- [ ] Login page renders
- [ ] Invalid credentials → error message
- [ ] Successful login → redirect to dashboard
- [ ] Token in localStorage
- [ ] All API calls include Authorization header
- [ ] WebSocket authenticates with token
- [ ] Logout clears token + redirects
- [ ] 401 response → auto-redirect to login
- [ ] Broker credentials UI saves + validates
- [ ] Settings page shows per-user preferences

## Regression Testing

```bash
# All existing backend tests (should still pass)
pytest tests/ -x -q

# New multi-user tests
pytest tests/test_multiuser.py -v

# Frontend build
cd frontend && npm run build

# E2E tests (with test users)
cd frontend && npx playwright test
```

## Rollback Plan

If multi-user migration fails:
1. Stop server
2. Restore SQLite database from backup
3. Revert code to pre-multiuser branch
4. Change `DATABASE_URL` back to SQLite
5. Restart server

Keep SQLite backup for at least 30 days after successful migration.

## Security Checklist

- [ ] Passwords hashed with bcrypt (never stored plaintext)
- [ ] Broker credentials encrypted with Fernet (AES-128)
- [ ] JWT secret in .env (not in code)
- [ ] Encryption key in .env (not in code)
- [ ] HTTPS enabled in production
- [ ] CORS restricted to frontend domain
- [ ] Rate limiting on auth endpoints (prevent brute force)
- [ ] SQL injection prevention (parameterized queries via SQLAlchemy ORM)
- [ ] No user_id in JWT payload visible to client (use opaque tokens if needed)
- [ ] Audit log for admin actions (optional but recommended)
