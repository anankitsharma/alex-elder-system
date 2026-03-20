# Phase 2: User Model + JWT Authentication

## Dependencies

```bash
pip install "fastapi-users[sqlalchemy]" python-jose[cryptography] passlib[bcrypt]
```

## New Files

### 2.1 `backend/app/models/user.py`

```python
from datetime import datetime
from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    trading_mode: Mapped[str] = mapped_column(String(10), default="PAPER")  # PAPER or LIVE

    # Risk settings (per-user overrides)
    max_risk_per_trade_pct: Mapped[float] = mapped_column(Float, default=2.0)
    max_portfolio_risk_pct: Mapped[float] = mapped_column(Float, default=6.0)
    min_signal_score: Mapped[int] = mapped_column(Integer, default=65)
    paper_starting_capital: Mapped[float] = mapped_column(Float, default=100000.0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserBrokerCredentials(Base):
    """Encrypted Angel One API credentials per user."""
    __tablename__ = "user_broker_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    exchange: Mapped[str] = mapped_column(String(20), default="ANGEL_ONE")

    # All credentials encrypted with Fernet (AES-128-CBC)
    encrypted_api_key: Mapped[str] = mapped_column(Text, default="")
    encrypted_secret_key: Mapped[str] = mapped_column(Text, default="")
    encrypted_client_code: Mapped[str] = mapped_column(Text, default="")
    encrypted_password: Mapped[str] = mapped_column(Text, default="")
    encrypted_totp_secret: Mapped[str] = mapped_column(Text, default="")

    # Historical + Feed API keys (optional, separate rate limits)
    encrypted_hist_api_key: Mapped[str] = mapped_column(Text, default="")
    encrypted_hist_secret: Mapped[str] = mapped_column(Text, default="")
    encrypted_feed_api_key: Mapped[str] = mapped_column(Text, default="")
    encrypted_feed_secret: Mapped[str] = mapped_column(Text, default="")

    is_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    last_validated_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UserNotificationConfig(Base):
    """Per-user notification preferences."""
    __tablename__ = "user_notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), unique=True)

    telegram_chat_id: Mapped[str] = mapped_column(String(50), default="")
    discord_webhook_url: Mapped[str] = mapped_column(Text, default="")

    # Alert preferences
    min_priority: Mapped[int] = mapped_column(Integer, default=1)  # 1=LOW, 2=NORMAL, 3=HIGH, 4=CRITICAL
    quiet_hours_start: Mapped[str] = mapped_column(String(5), default="")  # "23:00" or empty
    quiet_hours_end: Mapped[str] = mapped_column(String(5), default="")    # "07:00" or empty
    alerts_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
```

### 2.2 `backend/app/middleware/auth.py`

```python
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status, WebSocket
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=ALGORITHM)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """FastAPI dependency — extract and validate user from JWT."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


async def get_ws_user(websocket: WebSocket) -> Optional[User]:
    """Extract user from WebSocket query param ?token=JWT."""
    token = websocket.query_params.get("token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        async with async_session() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            return result.scalar_one_or_none()
    except Exception:
        return None
```

### 2.3 `backend/app/api/auth.py`

```python
# Endpoints:
# POST /api/auth/register  {email, username, password, full_name}
# POST /api/auth/login      {username, password} → {access_token, token_type}
# GET  /api/auth/me         → User profile
# POST /api/auth/broker     {api_key, secret, client_code, password, totp_secret}
# POST /api/auth/broker/validate  → Test broker connection
```

### 2.4 Config additions

```python
# config.py
jwt_secret: str = "change-me-in-production"  # from .env: JWT_SECRET
credential_encryption_key: str = ""           # from .env: CREDENTIAL_KEY (Fernet key)
```

## Auth Flow

```
1. User registers → POST /api/auth/register → User created in DB
2. User logs in → POST /api/auth/login → JWT returned
3. Frontend stores JWT in localStorage
4. All API calls include: Authorization: Bearer <JWT>
5. WebSocket connects with: /ws/pipeline?token=<JWT>
6. User adds broker creds → POST /api/auth/broker → Encrypted + stored
7. On pipeline start, broker session created with user's decrypted creds
```

## Migration

Create initial admin user via CLI or first-run:
```python
# backend/scripts/create_admin.py
# Creates first superuser with current .env broker credentials
```
