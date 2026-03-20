"""Seed system roles and permissions on first startup."""

from loguru import logger
from sqlalchemy import select

from app.database import async_session
from app.models.user import Role, Permission, role_permissions


# Permission definitions: (name, category)
PERMISSIONS = [
    # Market data
    ("data:view", "data"),
    ("signals:view", "data"),
    ("indicators:view", "data"),
    # Trading
    ("order:create", "trading"),
    ("order:modify", "trading"),
    ("order:cancel", "trading"),
    ("position:close", "trading"),
    # Pipeline
    ("pipeline:start", "pipeline"),
    ("pipeline:stop", "pipeline"),
    # Portfolio
    ("portfolio:view_own", "portfolio"),
    ("portfolio:view_all", "portfolio"),
    # Risk
    ("risk:view", "risk"),
    ("risk:modify", "risk"),
    ("circuit_breaker:reset", "risk"),
    # User management
    ("user:create", "admin"),
    ("user:modify", "admin"),
    ("user:disable", "admin"),
    ("user:view_all", "admin"),
    # System
    ("config:modify", "admin"),
    ("trading_mode:approve", "admin"),
    ("audit:view", "admin"),
]

# Role definitions: (name, description, is_system, permission_names)
ROLES = [
    ("super_admin", "Full system control", True, [p[0] for p in PERMISSIONS]),
    ("admin", "Risk manager — view all, modify risk", True, [
        "data:view", "signals:view", "indicators:view",
        "pipeline:start", "pipeline:stop",
        "portfolio:view_own", "portfolio:view_all",
        "risk:view", "risk:modify", "circuit_breaker:reset",
        "user:view_all", "audit:view",
    ]),
    ("trader", "Place orders, manage own pipeline", True, [
        "data:view", "signals:view", "indicators:view",
        "order:create", "order:modify", "order:cancel", "position:close",
        "pipeline:start", "pipeline:stop",
        "portfolio:view_own",
        "risk:view",
    ]),
    ("viewer", "Read-only access", True, [
        "data:view", "signals:view", "indicators:view",
        "portfolio:view_own",
        "risk:view",
    ]),
]


async def seed_roles_and_permissions():
    """Create system roles and permissions if they don't exist."""
    async with async_session() as session:
        # Check if roles already exist
        existing = await session.execute(select(Role).limit(1))
        if existing.scalar_one_or_none():
            return  # Already seeded

        logger.info("Seeding roles and permissions...")

        # Create permissions
        perm_map: dict[str, Permission] = {}
        for name, category in PERMISSIONS:
            perm = Permission(name=name, category=category)
            session.add(perm)
            perm_map[name] = perm
        await session.flush()  # Get IDs

        # Create roles with permissions
        for name, desc, is_system, perm_names in ROLES:
            role = Role(name=name, description=desc, is_system=is_system)
            role.permissions = [perm_map[p] for p in perm_names if p in perm_map]
            session.add(role)

        await session.commit()
        logger.info("Seeded {} roles and {} permissions", len(ROLES), len(PERMISSIONS))
