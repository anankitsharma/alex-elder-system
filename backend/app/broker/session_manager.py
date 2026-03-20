"""Per-user broker session manager — maintains authenticated AngelClient instances."""

from datetime import datetime, timedelta
from typing import Optional
from loguru import logger

from app.config import settings


class BrokerSessionManager:
    """Manages per-user Angel One broker sessions with encrypted credential storage."""

    SESSION_TTL = timedelta(hours=8)

    def __init__(self):
        self._sessions: dict[int, object] = {}  # user_id -> AngelClient
        self._session_times: dict[int, datetime] = {}
        self._fernet = None
        if settings.credential_encryption_key:
            try:
                from cryptography.fernet import Fernet
                self._fernet = Fernet(settings.credential_encryption_key.encode())
            except Exception as e:
                logger.warning("Credential encryption key invalid: {}", e)

    def encrypt(self, plaintext: str) -> str:
        if not plaintext or not self._fernet:
            return ""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, encrypted: str) -> str:
        if not encrypted or not self._fernet:
            return ""
        try:
            return self._fernet.decrypt(encrypted.encode()).decode()
        except Exception:
            return ""

    async def get_session(self, user_id: int):
        """Get or create an authenticated broker session for a user. Returns AngelClient or None."""
        # Check cache + TTL
        if user_id in self._sessions:
            age = datetime.now() - self._session_times.get(user_id, datetime.min)
            if age < self.SESSION_TTL:
                return self._sessions[user_id]
            del self._sessions[user_id]

        # Load encrypted credentials from DB
        from app.database import async_session
        from sqlalchemy import select
        from app.models.user import UserBrokerCredentials

        async with async_session() as session:
            stmt = select(UserBrokerCredentials).where(UserBrokerCredentials.user_id == user_id)
            result = await session.execute(stmt)
            creds = result.scalar_one_or_none()

        if not creds or not creds.encrypted_api_key:
            return None

        # Create client (don't actually call broker login - that would fail without valid creds)
        try:
            from app.broker.angel_client import AngelClient
            client = AngelClient()
            # Store decrypted creds for later use
            client._user_api_key = self.decrypt(creds.encrypted_api_key)
            client._user_client_code = self.decrypt(creds.encrypted_client_code)
            self._sessions[user_id] = client
            self._session_times[user_id] = datetime.now()
            logger.info("Broker session cached for user {}", user_id)
            return client
        except Exception as e:
            logger.error("Broker session creation failed for user {}: {}", user_id, e)
            return None

    def remove_session(self, user_id: int):
        self._sessions.pop(user_id, None)
        self._session_times.pop(user_id, None)

    async def save_credentials(self, user_id: int, creds: dict) -> bool:
        """Encrypt and save broker credentials for a user."""
        from app.database import async_session
        from sqlalchemy import select
        from app.models.user import UserBrokerCredentials

        async with async_session() as session:
            stmt = select(UserBrokerCredentials).where(UserBrokerCredentials.user_id == user_id)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()

            if not record:
                record = UserBrokerCredentials(user_id=user_id)
                session.add(record)

            record.encrypted_api_key = self.encrypt(creds.get("api_key", ""))
            record.encrypted_secret_key = self.encrypt(creds.get("secret_key", ""))
            record.encrypted_client_code = self.encrypt(creds.get("client_code", ""))
            record.encrypted_password = self.encrypt(creds.get("password", ""))
            record.encrypted_totp_secret = self.encrypt(creds.get("totp_secret", ""))
            record.encrypted_hist_api_key = self.encrypt(creds.get("hist_api_key", ""))
            record.encrypted_hist_secret = self.encrypt(creds.get("hist_secret", ""))
            record.encrypted_feed_api_key = self.encrypt(creds.get("feed_api_key", ""))
            record.encrypted_feed_secret = self.encrypt(creds.get("feed_secret", ""))

            await session.commit()
            self.remove_session(user_id)  # Clear cached session
            return True


# Singleton
broker_sessions = BrokerSessionManager()
