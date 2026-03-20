"""Tests for multi-user authentication system."""

import sys
import os
import pytest

_backend_dir = os.path.join(os.path.dirname(__file__), "..", "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_dir))

from backend.app.middleware.auth import (
    hash_password, verify_password, create_access_token,
    Role, ROLE_HIERARCHY,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        password = "test-password-123"
        hashed = hash_password(password)
        assert hashed != password
        assert verify_password(password, hashed) is True

    def test_wrong_password_fails(self):
        hashed = hash_password("correct-password")
        assert verify_password("wrong-password", hashed) is False

    def test_different_hashes_for_same_password(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # bcrypt uses random salt


class TestJWTTokens:
    def test_create_token(self):
        token = create_access_token(user_id=1, role="trader")
        assert isinstance(token, str)
        assert len(token) > 50  # JWT is at least ~100 chars

    def test_decode_token(self):
        from jose import jwt
        from backend.app.config import settings

        token = create_access_token(user_id=42, role="admin")
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        assert payload["sub"] == "42"
        assert payload["role"] == "admin"
        assert "exp" in payload

    def test_expired_token_raises(self):
        from datetime import timedelta
        from jose import jwt, ExpiredSignatureError
        from backend.app.config import settings

        token = create_access_token(
            user_id=1, role="trader",
            expires_delta=timedelta(seconds=-1),  # Already expired
        )
        with pytest.raises(ExpiredSignatureError):
            jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])


class TestRoleHierarchy:
    def test_super_admin_is_highest(self):
        assert ROLE_HIERARCHY[Role.SUPER_ADMIN] < ROLE_HIERARCHY[Role.ADMIN]
        assert ROLE_HIERARCHY[Role.SUPER_ADMIN] < ROLE_HIERARCHY[Role.TRADER]
        assert ROLE_HIERARCHY[Role.SUPER_ADMIN] < ROLE_HIERARCHY[Role.VIEWER]

    def test_trader_above_viewer(self):
        assert ROLE_HIERARCHY[Role.TRADER] < ROLE_HIERARCHY[Role.VIEWER]

    def test_admin_above_trader(self):
        assert ROLE_HIERARCHY[Role.ADMIN] < ROLE_HIERARCHY[Role.TRADER]

    def test_all_roles_defined(self):
        assert len(ROLE_HIERARCHY) == 4
        for role in Role:
            assert role in ROLE_HIERARCHY


class TestRoleEnum:
    def test_role_values(self):
        assert Role.SUPER_ADMIN.value == "super_admin"
        assert Role.ADMIN.value == "admin"
        assert Role.TRADER.value == "trader"
        assert Role.VIEWER.value == "viewer"

    def test_role_from_string(self):
        assert Role("super_admin") == Role.SUPER_ADMIN
        assert Role("trader") == Role.TRADER


class TestUserModel:
    """Model field tests — use app.models (not backend.app.models) to avoid dual-import."""

    def test_user_model_fields(self):
        from app.models.user import User
        for field in ["email", "username", "hashed_password", "role_id",
                      "trading_mode", "approved_for_live",
                      "max_risk_per_trade_pct", "max_portfolio_risk_pct"]:
            assert hasattr(User, field), f"User missing field: {field}"

    def test_broker_credentials_model(self):
        from app.models.user import UserBrokerCredentials
        for field in ["user_id", "encrypted_api_key", "encrypted_totp_secret", "is_validated"]:
            assert hasattr(UserBrokerCredentials, field)

    def test_access_request_model(self):
        from app.models.user import AccessRequest
        for field in ["user_id", "request_type", "status", "reviewed_by"]:
            assert hasattr(AccessRequest, field)

    def test_role_model(self):
        from app.models.user import Role as RoleModel
        for field in ["name", "is_system", "permissions"]:
            assert hasattr(RoleModel, field)

    def test_notification_config_model(self):
        from app.models.user import UserNotificationConfig
        for field in ["telegram_chat_id", "discord_webhook_url", "min_priority", "alerts_enabled"]:
            assert hasattr(UserNotificationConfig, field)
