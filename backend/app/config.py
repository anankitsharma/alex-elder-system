"""Application configuration loaded from .env file."""

from pathlib import Path
from pydantic import model_validator
from pydantic_settings import BaseSettings
from loguru import logger


class Settings(BaseSettings):
    # Angel One Trading API
    angel_api_key: str = ""
    angel_secret_key: str = ""
    angel_client_code: str = ""
    angel_client_password: str = ""
    angel_totp_secret: str = ""

    # Angel One Historical API
    angel_hist_api_key: str = ""
    angel_hist_api_secret: str = ""

    # Angel One WebSocket Feed API
    angel_feed_api_key: str = ""
    angel_feed_api_secret: str = ""

    # Notifications
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook_url: str = ""  # Discord webhook for trade alerts

    # App settings
    # PostgreSQL: "postgresql+asyncpg://user:pass@localhost:5432/elder_trading"
    # SQLite (default for dev): "sqlite+aiosqlite:///./elder_trading.db"
    db_url: str = "sqlite+aiosqlite:///./elder_trading.db"
    log_level: str = "INFO"
    trading_mode: str = "PAPER"  # PAPER or LIVE (global default, per-user overrides)

    # Auth (multi-user)
    jwt_secret: str = "elder-dev-secret-change-in-production"
    jwt_expire_minutes: int = 1440  # 24 hours
    credential_encryption_key: str = ""  # Fernet key for encrypting broker creds

    # Risk defaults
    max_risk_per_trade_pct: float = 2.0
    max_portfolio_risk_pct: float = 6.0
    min_signal_score: int = 65
    paper_starting_capital: float = 100000.0  # Default equity for PAPER mode
    paper_slippage_pct: float = 0.1  # Simulated slippage for paper trading (%)

    # Anti-spam alert thresholds
    tide_dead_zone: float = 0.005       # MACD-H slope below this → NEUTRAL
    wave_fi2_dead_zone: float = 0.01    # Force Index(2) abs below this → 0
    flip_confirm_bars: int = 2           # Consecutive bars to confirm tide flip
    wave_confirm_bars: int = 2           # Consecutive bars to confirm wave change

    # Rate limiting
    max_orders_per_minute: int = 10

    model_config = {
        "env_file": str(Path(__file__).resolve().parents[2] / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @model_validator(mode="after")
    def validate_credentials(self) -> "Settings":
        """Validate that required credentials exist for LIVE mode."""
        required_live = [
            "angel_api_key", "angel_client_code",
            "angel_client_password", "angel_totp_secret",
        ]
        if self.trading_mode == "LIVE":
            missing = [k for k in required_live if not getattr(self, k)]
            if missing:
                raise ValueError(
                    f"LIVE mode requires: {', '.join(missing)}. "
                    "Set them in .env or switch to PAPER mode."
                )
        else:
            # In PAPER mode, just warn
            missing = [k for k in required_live if not getattr(self, k)]
            if missing:
                logger.warning(
                    "Missing credentials ({}). Broker features unavailable.",
                    ", ".join(missing),
                )
        return self


settings = Settings()

# Multi-asset tracking list for F&O pipeline
TRACKED_INSTRUMENTS = [
    # NFO Index Futures
    ("NIFTY", "NFO"),
    ("BANKNIFTY", "NFO"),
    # MCX Metals
    ("GOLDM", "MCX"),
    ("SILVERM", "MCX"),
    ("COPPER", "MCX"),
    ("ALUMINIUM", "MCX"),
    ("ZINC", "MCX"),
    # MCX Energy
    ("NATGASMINI", "MCX"),
    ("CRUDEOILM", "MCX"),
]
