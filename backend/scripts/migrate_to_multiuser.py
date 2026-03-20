"""One-time migration: convert single-user system to multi-user.

Creates the first admin user from current .env credentials and assigns
all existing data (positions, orders, trades, signals) to that user.

Usage:
    cd backend
    python -m scripts.migrate_to_multiuser
"""

import asyncio
import sys
import os

# Ensure backend/ is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger


async def migrate():
    from app.database import async_session, init_db
    from app.seed import seed_roles_and_permissions
    from app.config import settings
    from app.middleware.auth import hash_password
    from app.models.user import User, Role as RoleModel, UserNotificationConfig
    from app.models.trade import Order, Position, Trade
    from app.models.signal import Signal
    from app.models.config import PortfolioRisk
    from sqlalchemy import select, update

    # 1. Create tables (including new ones)
    await init_db()
    logger.info("Database tables created/verified")

    # 2. Seed roles and permissions
    await seed_roles_and_permissions()
    logger.info("Roles and permissions seeded")

    # 3. Create admin user
    async with async_session() as session:
        existing = await session.execute(select(User).where(User.id == 1))
        if existing.scalar_one_or_none():
            logger.info("Admin user already exists (id=1), skipping creation")
        else:
            # Get super_admin role
            role_result = await session.execute(
                select(RoleModel).where(RoleModel.name == "super_admin")
            )
            sa_role = role_result.scalar_one_or_none()

            admin = User(
                email="admin@elder.local",
                username="admin",
                hashed_password=hash_password("admin123"),  # Change after first login!
                full_name="System Admin",
                role_id=sa_role.id if sa_role else 1,
                trading_mode=settings.trading_mode,
                approved_for_live=True,
                max_risk_per_trade_pct=settings.max_risk_per_trade_pct,
                max_portfolio_risk_pct=settings.max_portfolio_risk_pct,
                min_signal_score=settings.min_signal_score,
                paper_starting_capital=settings.paper_starting_capital,
            )
            session.add(admin)
            await session.commit()
            await session.refresh(admin)
            logger.info("Created admin user: id={} email={}", admin.id, admin.email)

            # Create notification config from .env
            if settings.telegram_chat_id:
                notif = UserNotificationConfig(
                    user_id=admin.id,
                    telegram_chat_id=settings.telegram_chat_id,
                    discord_webhook_url=settings.discord_webhook_url,
                )
                session.add(notif)
                await session.commit()
                logger.info("Migrated notification config for admin")

    # 4. Assign existing data to admin user (user_id=1)
    async with async_session() as session:
        tables_to_update = [
            (Order, "orders"),
            (Position, "positions"),
            (Trade, "trades"),
            (Signal, "signals"),
            (PortfolioRisk, "portfolio_risk"),
        ]

        for model, name in tables_to_update:
            stmt = (
                update(model)
                .where(model.user_id == None)  # noqa: E711
                .values(user_id=1)
            )
            result = await session.execute(stmt)
            count = result.rowcount
            if count > 0:
                logger.info("Assigned {} {} records to admin (user_id=1)", count, name)

        await session.commit()

    # 5. Encrypt broker credentials for admin (if available)
    if settings.credential_encryption_key and settings.angel_api_key:
        try:
            from app.broker.session_manager import broker_sessions
            await broker_sessions.save_credentials(1, {
                "api_key": settings.angel_api_key,
                "secret_key": settings.angel_secret_key,
                "client_code": settings.angel_client_code,
                "password": settings.angel_client_password,
                "totp_secret": settings.angel_totp_secret,
                "hist_api_key": settings.angel_hist_api_key,
                "hist_secret": settings.angel_hist_api_secret,
                "feed_api_key": settings.angel_feed_api_key,
                "feed_secret": settings.angel_feed_api_secret,
            })
            logger.info("Encrypted and stored broker credentials for admin")
        except Exception as e:
            logger.warning("Broker credential migration skipped: {}", e)
    else:
        logger.info("No credential encryption key set — broker creds not migrated")

    logger.info("Migration complete! Admin user: admin@elder.local / admin123")
    logger.info("IMPORTANT: Change the admin password after first login!")


if __name__ == "__main__":
    asyncio.run(migrate())
