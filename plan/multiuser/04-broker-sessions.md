# Phase 4: Per-User Broker Sessions

## Problem

Currently one `angel = AngelClient()` singleton handles ALL broker operations. Multi-user requires each user to trade with their own Angel One account.

## Architecture

```
BrokerSessionManager (singleton)
├── user_1 → AngelClient (API keys from DB, encrypted)
├── user_2 → AngelClient (API keys from DB, encrypted)
└── user_N → AngelClient (API keys from DB, encrypted)
```

**Market data feed stays shared** — one `MarketFeed` connection for tick data (uses system-level feed API keys from .env). Individual user trading uses per-user sessions.

## New File: `backend/app/broker/session_manager.py`

```python
"""Per-user broker session manager.

Maintains a pool of authenticated AngelClient instances, one per user.
Sessions are created lazily on first access and cached with TTL.
"""

from datetime import datetime, timedelta
from typing import Optional
from cryptography.fernet import Fernet
from loguru import logger

from app.config import settings
from app.broker.angel_client import AngelClient
from app.database import async_session
from app.models.user import UserBrokerCredentials


class BrokerSessionManager:
    """Manages per-user Angel One broker sessions."""

    SESSION_TTL = timedelta(hours=8)  # Re-auth after 8 hours

    def __init__(self):
        self._sessions: dict[int, AngelClient] = {}       # user_id -> client
        self._session_times: dict[int, datetime] = {}      # user_id -> last_auth
        self._fernet: Optional[Fernet] = None
        if settings.credential_encryption_key:
            self._fernet = Fernet(settings.credential_encryption_key.encode())

    def _decrypt(self, encrypted: str) -> str:
        if not encrypted or not self._fernet:
            return ""
        return self._fernet.decrypt(encrypted.encode()).decode()

    def _encrypt(self, plaintext: str) -> str:
        if not plaintext or not self._fernet:
            return ""
        return self._fernet.encrypt(plaintext.encode()).decode()

    async def get_session(self, user_id: int) -> Optional[AngelClient]:
        """Get or create an authenticated broker session for a user."""
        # Check cache + TTL
        if user_id in self._sessions:
            age = datetime.now() - self._session_times.get(user_id, datetime.min)
            if age < self.SESSION_TTL:
                return self._sessions[user_id]
            # Expired — re-auth
            del self._sessions[user_id]

        # Load credentials from DB
        async with async_session() as session:
            from sqlalchemy import select
            stmt = select(UserBrokerCredentials).where(
                UserBrokerCredentials.user_id == user_id
            )
            result = await session.execute(stmt)
            creds = result.scalar_one_or_none()

        if not creds or not creds.encrypted_api_key:
            return None

        # Create and authenticate client
        try:
            client = AngelClient()
            client.login_with_credentials(
                api_key=self._decrypt(creds.encrypted_api_key),
                secret_key=self._decrypt(creds.encrypted_secret_key),
                client_code=self._decrypt(creds.encrypted_client_code),
                password=self._decrypt(creds.encrypted_password),
                totp_secret=self._decrypt(creds.encrypted_totp_secret),
            )
            self._sessions[user_id] = client
            self._session_times[user_id] = datetime.now()
            logger.info("Broker session created for user {}", user_id)
            return client
        except Exception as e:
            logger.error("Broker auth failed for user {}: {}", user_id, e)
            return None

    def remove_session(self, user_id: int):
        """Remove a user's broker session (logout)."""
        self._sessions.pop(user_id, None)
        self._session_times.pop(user_id, None)

    async def save_credentials(self, user_id: int, creds: dict) -> bool:
        """Encrypt and save broker credentials for a user."""
        async with async_session() as session:
            from sqlalchemy import select
            stmt = select(UserBrokerCredentials).where(
                UserBrokerCredentials.user_id == user_id
            )
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()

            if not record:
                record = UserBrokerCredentials(user_id=user_id)
                session.add(record)

            record.encrypted_api_key = self._encrypt(creds.get("api_key", ""))
            record.encrypted_secret_key = self._encrypt(creds.get("secret_key", ""))
            record.encrypted_client_code = self._encrypt(creds.get("client_code", ""))
            record.encrypted_password = self._encrypt(creds.get("password", ""))
            record.encrypted_totp_secret = self._encrypt(creds.get("totp_secret", ""))

            await session.commit()
            return True


# Singleton
broker_sessions = BrokerSessionManager()
```

## Changes to `AngelClient`

Add a `login_with_credentials()` method that accepts explicit credentials instead of reading from `.env`:

```python
def login_with_credentials(self, api_key, secret_key, client_code, password, totp_secret):
    """Authenticate with explicitly provided credentials (for multi-user)."""
    # Same logic as login_trading() but uses provided params instead of settings.*
```

## Changes to Execution Layer

**`trading/live.py`**: `LivePlacer` must accept an `AngelClient` instance instead of importing the global singleton.

```python
class LivePlacer:
    def __init__(self, angel_client: AngelClient):
        self._angel = angel_client

    async def place_entry(self, ...):
        result = await asyncio.wait_for(
            asyncio.to_thread(self._angel.place_order, ...),
            timeout=BROKER_TIMEOUT,
        )
```

**`asset_session.py`**: `_init_executor()` looks up the user's broker session:

```python
def _init_executor(self):
    if self.user.trading_mode == "LIVE":
        angel_client = await broker_sessions.get_session(self.user_id)
        placer = LivePlacer(angel_client)
    else:
        placer = PaperPlacer(slippage_pct=0.0)
    self.executor = TradeExecutor(placer, on_notify=self._on_executor_event)
```

## Market Data Feed (Stays Shared)

The `market_feed` singleton continues to use system-level feed API keys from `.env`. This is because:
1. Angel One charges per WebSocket connection
2. Market data is identical for all users
3. One connection is sufficient for all tracked symbols

Only **trading operations** (place_order, cancel_order, get_order_book) use per-user sessions.

## Credential Encryption

```python
# Generate encryption key (one-time):
from cryptography.fernet import Fernet
key = Fernet.generate_key()
print(key.decode())  # Add to .env as CREDENTIAL_KEY
```

Store in `.env`:
```
CREDENTIAL_KEY=gAAAAABk...  # Fernet key
```
